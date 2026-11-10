"""Record-level recovery from a verified Mei backup.

Category restore intentionally replaces whole files; it is the right operation
when a profile is broadly damaged, but it is too blunt when one note or one
task was deleted.  This module restores a single record through the existing
store writer, after validating the backup record and creating a full
pre-restore backup.

Only stores with stable IDs and a known writer are supported.  Unsupported
stores are refused rather than guessed at with a generic JSON merge.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
import zipfile
from dataclasses import dataclass

from litebrowser.core import prefs, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import safe_child_path, write_json, write_text_atomic
from litebrowser.services import (
    backup_service,
    flashcard_service,
    life_service,
    link_service,
    personal_plan,
    personal_service,
    tab_sets,
)

_log = get_logger("record_restore_service")

NOTES_STORE = "notes"
HISTORY_RELPATH = os.path.join("Recovery", "record_restore_history.json")
MAX_RECORD_BYTES = 4 * 1024 * 1024


class RecordRestoreError(OSError):
    """The selected record cannot be restored safely."""


@dataclass(frozen=True)
class _Adapter:
    key: str
    label: str
    store_name: str
    collection: str
    load: object
    save: object
    id_key: str = "id"


def _plan_items(base_dir: str) -> list[dict]:
    plan = personal_plan.load_plan(base_dir)
    rows = plan.get("items") if isinstance(plan, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save_plan_items(base_dir: str, rows: list[dict]) -> None:
    plan = personal_plan.load_plan(base_dir)
    if not isinstance(plan, dict):
        raise RecordRestoreError("The planner does not contain an object")
    plan["items"] = rows
    personal_plan.save_plan(base_dir, plan)


def _tab_set_rows(base_dir: str) -> list[dict]:
    data = tab_sets.load_tab_sets(base_dir)
    rows = data.get("sets") if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save_tab_set_rows(base_dir: str, rows: list[dict]) -> None:
    data = tab_sets.load_tab_sets(base_dir)
    if not isinstance(data, dict):
        raise RecordRestoreError("The tab-set store does not contain an object")
    data["sets"] = rows
    tab_sets.save_tab_sets(base_dir, data)


ADAPTERS = {
    "tasks": _Adapter("tasks", "Quick tasks", "tasks.json", "", life_service.load_tasks, life_service.save_tasks),
    "events": _Adapter("events", "Calendar", "calendar.json", "", life_service.load_events, life_service.save_events),
    "boards": _Adapter("boards", "Idea boards", "boards.json", "", life_service.load_boards, life_service.save_boards),
    "saved_pages": _Adapter(
        "saved_pages", "Saved pages", "saved_pages.json", "", life_service.load_saved_pages, life_service.save_saved_pages
    ),
    "flashcards": _Adapter(
        "flashcards", "Flashcards", "flashcards.json", "cards", flashcard_service.load_cards, flashcard_service.save_cards
    ),
    "planner": _Adapter(
        "planner", "Planner items", "personal_plan.json", "items", _plan_items, _save_plan_items
    ),
    "bookmarks": _Adapter(
        "bookmarks", "Bookmarks", "bookmarks.json", "", prefs.load_bookmarks, prefs.save_bookmarks, "url"
    ),
    "tab_sets": _Adapter(
        "tab_sets", "Tab sets / research", "tab_sets.json", "sets", _tab_set_rows, _save_tab_set_rows
    ),
    "entity_links": _Adapter(
        "entity_links", "Entity links", "entity_links.json", "links", link_service.load_links, link_service.save_links
    ),
}
SUPPORTED_STORES = tuple(ADAPTERS) + (NOTES_STORE,)


def _check_backup(backup_path: str) -> dict:
    checked = backup_service.verify_backup(backup_path)
    if not checked["ok"]:
        raise RecordRestoreError("; ".join(checked["errors"]) or "The backup is not valid.")
    return checked


def _read_zip_json(archive: zipfile.ZipFile, path: str):
    try:
        info = archive.getinfo(path)
    except KeyError as exc:
        raise RecordRestoreError(f"{path} is not in this backup") from exc
    if info.file_size > MAX_RECORD_BYTES:
        raise RecordRestoreError(f"{path} is too large for record-level restore")
    try:
        return json.loads(archive.read(info).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RecordRestoreError(f"{path} is not readable JSON: {exc}") from exc


def _backup_record(backup_path: str, store: str, record_id: str):
    if store not in ADAPTERS:
        raise RecordRestoreError("That store does not support record-level restore.")
    adapter = ADAPTERS[store]
    with zipfile.ZipFile(backup_path, "r") as archive:
        payload = _read_zip_json(archive, adapter.store_name)
    rows = payload if isinstance(payload, list) else payload.get(adapter.collection, []) if isinstance(payload, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and str(row.get(adapter.id_key)) == str(record_id):
            return copy.deepcopy(row)
    raise RecordRestoreError("That record is not present in the selected backup.")


def _current_record(base_dir: str, store: str, record_id: str):
    if store not in ADAPTERS:
        raise RecordRestoreError("That store does not support record-level restore.")
    rows = ADAPTERS[store].load(base_dir) or []
    return next(
        (
            copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict) and str(row.get(ADAPTERS[store].id_key)) == str(record_id)
        ),
        None,
    )


def _note_path(base_dir: str, record_id: str) -> str:
    relative = _normalize_note_id(record_id)
    path = safe_child_path(base_dir, relative)
    if not path:
        raise RecordRestoreError("The note id points outside this profile.")
    return path


def _normalize_note_id(record_id: str) -> str:
    """Accept the Windows relative id returned by personal_service."""
    relative = str(record_id or "").replace("\\", "/").lstrip("/")
    if not relative.startswith("SafeVault/notes/"):
        relative = "SafeVault/notes/" + relative
    if relative == "SafeVault/notes/" or ".." in relative.split("/"):
        raise RecordRestoreError("The note id is not a SafeVault note path.")
    return relative


def _backup_note(backup_path: str, record_id: str) -> tuple[str, dict]:
    relative = _normalize_note_id(record_id)
    with zipfile.ZipFile(backup_path, "r") as archive:
        try:
            info = archive.getinfo(relative)
        except KeyError as exc:
            raise RecordRestoreError("That note is not present in the selected backup.") from exc
        if info.file_size > MAX_RECORD_BYTES:
            raise RecordRestoreError("That note is too large to restore as one record.")
        try:
            text = archive.read(info).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RecordRestoreError("That note is not valid UTF-8.") from exc
    title = os.path.splitext(os.path.basename(relative))[0]
    category = os.path.dirname(relative[len("SafeVault/notes/"):]).replace("\\", "/").strip("/") or "General"
    return text, {"id": relative, "title": title, "category": category, "content": text}


def list_records(backup_path: str, store: str) -> list[dict]:
    """List restorable record ids for the UI, without exposing note bodies."""
    if store == NOTES_STORE:
        _check_backup(backup_path)
        with zipfile.ZipFile(backup_path, "r") as archive:
            result = []
            for name in archive.namelist():
                if not name.startswith("SafeVault/notes/") or not name.lower().endswith((".md", ".txt")):
                    continue
                stem = os.path.splitext(os.path.basename(name))[0]
                result.append({"id": name, "title": stem, "updated_at": 0})
            return sorted(result, key=lambda row: row["id"].lower())[:5000]
    if store not in ADAPTERS:
        raise RecordRestoreError("Unknown record store.")
    _check_backup(backup_path)
    adapter = ADAPTERS[store]
    with zipfile.ZipFile(backup_path, "r") as archive:
        payload = _read_zip_json(archive, adapter.store_name)
    rows = payload if isinstance(payload, list) else payload.get(adapter.collection, []) if isinstance(payload, dict) else []
    result = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get(adapter.id_key):
            continue
        title = next(
            (str(row[key]) for key in ("title", "front", "name", "label", "url") if isinstance(row.get(key), str) and row.get(key)),
            str(row[adapter.id_key]),
        )
        result.append(
            {
                "id": str(row[adapter.id_key]),
                "title": title[:160],
                "updated_at": row.get("updated_at", 0),
            }
        )
    return result[:5000]


def preview(base_dir: str, backup_path: str, store: str, record_id: str) -> dict:
    """Show old/new values and whether replacing would overwrite a record."""
    _check_backup(backup_path)
    if store == NOTES_STORE:
        content, record = _backup_note(backup_path, record_id)
        current_path = _note_path(base_dir, record_id)
        current = None
        if os.path.isfile(current_path):
            with open(current_path, "r", encoding="utf-8", errors="replace") as handle:
                current_text = handle.read()
            current = {"id": record_id, "content": current_text}
        return {
            "ok": True,
            "store": store,
            "record_id": record_id,
            "backup": record,
            "current": current,
            "exists": current is not None,
            "changed": current is None or current.get("content") != content,
            "title": record["title"],
        }
    record = _backup_record(backup_path, store, record_id)
    current = _current_record(base_dir, store, record_id)
    return {
        "ok": True,
        "store": store,
        "record_id": record_id,
        "backup": record,
        "current": current,
        "exists": current is not None,
        "changed": current != record,
        "title": next(
            (str(record[key]) for key in ("title", "front", "name", "label", "url") if isinstance(record.get(key), str) and record.get(key)),
            str(record_id),
        )[:160],
    }


def _history(base_dir: str, row: dict) -> None:
    path = os.path.join(base_dir, HISTORY_RELPATH)
    current = storage_health.read_json_checked(path, dict)
    payload = dict(current.value) if current.ok else {"version": 1, "restores": []}
    restores = payload.get("restores")
    payload["restores"] = (restores if isinstance(restores, list) else [])[-200:] + [row]
    payload["version"] = 1
    try:
        write_json(path, payload, allow_replace_corrupt=True)
    except OSError as exc:
        _log.warning("record restore succeeded but history could not be written: %s", exc)


def restore(
    base_dir: str,
    backup_path: str,
    store: str,
    record_id: str,
    *,
    mode: str = "replace",
    confirm: bool = False,
) -> dict:
    """Restore one record, preserving both versions if anything fails.

    ``mode="replace"`` requires confirmation when a live record exists.
    ``mode="as_new"`` always allocates a new id (or a new note filename) so an
    existing record is never reused accidentally.
    """
    if mode not in ("replace", "as_new"):
        raise RecordRestoreError("mode must be 'replace' or 'as_new'")
    if not confirm:
        raise RecordRestoreError("Record restore requires explicit confirmation.")
    if store in ADAPTERS and ADAPTERS[store].id_key != "id" and mode == "as_new":
        raise RecordRestoreError(
            "This store is identified by its URL; restoring as new would duplicate an external reference. Use replace."
        )
    checked_plan = preview(base_dir, backup_path, store, record_id)
    if mode == "replace" and checked_plan["exists"] and not confirm:
        raise RecordRestoreError("Restoring over an existing record requires explicit confirmation.")
    if not checked_plan["changed"]:
        return {"ok": False, "status": "unchanged", "error": "The current record already matches the backup."}
    pre = backup_service.create_backup(base_dir, kind="pre-record-restore")
    if not pre.ok:
        return {"ok": False, "status": "blocked", "error": f"Could not create a pre-restore backup: {pre.error}"}
    try:
        with profile_locked(base_dir):
            if store == NOTES_STORE:
                text, record = _backup_note(backup_path, record_id)
                if mode == "as_new":
                    created = personal_service.create_note(
                        base_dir,
                        f"{record['title']} (restored)",
                        text,
                        record["category"],
                    )
                    if not created:
                        raise RecordRestoreError("The note could not be restored as a new file.")
                    result_id = created["id"]
                else:
                    target = _note_path(base_dir, record_id)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    write_text_atomic(target, text)
                    result_id = record_id
            else:
                adapter = ADAPTERS[store]
                row = _backup_record(backup_path, store, record_id)
                rows = list(adapter.load(base_dir) or [])
                index = next(
                    (
                        i
                        for i, item in enumerate(rows)
                        if isinstance(item, dict)
                        and str(item.get(adapter.id_key)) == str(record_id)
                    ),
                    None,
                )
                if mode == "as_new":
                    row = dict(row)
                    row[adapter.id_key] = uuid.uuid4().hex
                    rows.append(row)
                    result_id = row[adapter.id_key]
                elif index is None:
                    rows.append(row)
                    result_id = record_id
                else:
                    rows[index] = row
                    result_id = record_id
                adapter.save(base_dir, rows)
        _history(
            base_dir,
            {
                "at": int(time.time()),
                "store": store,
                "record_id": str(record_id),
                "result_id": str(result_id),
                "mode": mode,
                "backup": os.path.abspath(backup_path),
                "pre_restore_backup": pre.path,
            },
        )
        _log.info("record restore completed for %s (%s)", store, mode)
        return {
            "ok": True,
            "status": "restored",
            "store": store,
            "record_id": result_id,
            "pre_restore_backup": pre.path,
        }
    except (OSError, ValueError, RecordRestoreError) as exc:
        return {
            "ok": False,
            "status": "failed",
            "error": str(exc),
            "pre_restore_backup": pre.path,
        }


__all__ = [
    "ADAPTERS",
    "HISTORY_RELPATH",
    "NOTES_STORE",
    "RecordRestoreError",
    "SUPPORTED_STORES",
    "list_records",
    "preview",
    "restore",
]
