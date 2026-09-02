import base64
import json
import os
import shutil
import time
import uuid
import zipfile

from litebrowser.core import app_paths, prefs
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json, write_text_atomic
from litebrowser.services import tab_sets, workspace_manager


def activity_path(base_dir: str) -> str:
    return os.path.join(base_dir, "activity_history.json")


def load_activity(base_dir: str):
    data = read_json(activity_path(base_dir), {"version": 1, "events": []})
    if not isinstance(data, dict):
        return {"version": 1, "events": []}
    data.setdefault("version", 1)
    data.setdefault("events", [])
    return data


def save_activity(base_dir: str, data):
    payload = dict(data or {})
    payload.setdefault("version", 1)
    payload.setdefault("events", [])
    with profile_locked(base_dir):
        write_json(activity_path(base_dir), payload)


def clear_activity(base_dir: str) -> int:
    """Delete every activity record; returns how many events were removed."""
    removed = len(load_activity(base_dir).get("events", []))
    save_activity(base_dir, {"version": 1, "events": []})
    return removed


def log_event(base_dir: str, kind: str, title: str, detail: str = "", meta: dict | None = None):
    with profile_locked(base_dir):
        data = load_activity(base_dir)
        events = data.get("events", [])
        event = {
            "id": uuid.uuid4().hex,
            "ts": int(time.time()),
            "kind": (kind or "").strip() or "activity",
            "title": (title or "").strip(),
            "detail": (detail or "").strip(),
            "meta": meta if isinstance(meta, dict) else {},
        }
        events.insert(0, event)
        data["events"] = events[:3000]
        payload = dict(data)
        payload.setdefault("version", 1)
        payload.setdefault("events", [])
        write_json(activity_path(base_dir), payload)
        return event


def list_activity(base_dir: str, query: str = "", kind: str = ""):
    query = (query or "").strip().lower()
    kind = (kind or "").strip().lower()
    events = load_activity(base_dir).get("events", [])
    out = []
    for item in events:
        if kind and (item.get("kind", "").lower() != kind):
            continue
        hay = "\n".join(
            [
                item.get("kind", ""),
                item.get("title", ""),
                item.get("detail", ""),
                " ".join(f"{k}:{v}" for k, v in (item.get("meta") or {}).items()),
            ]
        ).lower()
        if query and query not in hay:
            continue
        out.append(item)
    return out


PROFILE_ZIP_JSON_MEMBER = "profile.json"
PROFILE_ZIP_VAULT_PREFIX = "vault/"
PROFILE_ZIP_BROWSER_PREFIX = "BrowserData/"


def _export_vault_files_excluding_notes(base_dir: str) -> list:
    """All SafeVault files except under notes/ (notes are in the notes[] export key)."""
    vault = prefs.vault_path(base_dir)
    out = []
    if not os.path.isdir(vault):
        return out
    notes_prefix = "notes/"
    for root, _, files in os.walk(vault):
        for fn in files:
            abspath = os.path.join(root, fn)
            rel = os.path.relpath(abspath, vault).replace("\\", "/")
            if rel == "notes" or rel.startswith(notes_prefix):
                continue
            try:
                size = os.path.getsize(abspath)
            except OSError:
                continue
            try:
                with open(abspath, "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            entry: dict = {"path": rel, "size": size}
            try:
                entry["encoding"] = "utf-8"
                entry["text"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                entry["encoding"] = "base64"
                entry["data"] = base64.standard_b64encode(raw).decode("ascii")
            out.append(entry)
    return out


def _import_vault_files(base_dir: str, entries) -> None:
    if not isinstance(entries, list):
        return
    vault = prefs.vault_path(base_dir)
    os.makedirs(vault, exist_ok=True)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        rel = (ent.get("path") or "").replace("\\", "/").strip().lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        if rel == "notes" or rel.startswith("notes/"):
            continue
        if ent.get("skipped_large"):
            continue
        vault_abs = os.path.abspath(vault)
        dest = os.path.normpath(os.path.join(vault_abs, *rel.split("/")))
        dest_abs = os.path.abspath(dest)
        if dest_abs != vault_abs and not dest_abs.startswith(vault_abs + os.sep):
            continue
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if ent.get("encoding") == "base64" and isinstance(ent.get("data"), str):
            try:
                raw = base64.standard_b64decode(ent["data"].encode("ascii"))
            except (ValueError, TypeError):
                continue
            try:
                with open(dest, "wb") as f:
                    f.write(raw)
            except OSError:
                continue
        elif ent.get("encoding") == "utf-8" and "text" in ent:
            try:
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(str(ent.get("text") or ""))
            except OSError:
                continue


def _add_vault_tree_to_zip(zf: zipfile.ZipFile, base_dir: str) -> None:
    """Append SafeVault files (except notes/) into zip under vault/."""
    vault = prefs.vault_path(base_dir)
    notes_prefix = "notes/"
    if not os.path.isdir(vault):
        return
    for root, _, files in os.walk(vault):
        for fn in files:
            abspath = os.path.join(root, fn)
            rel = os.path.relpath(abspath, vault).replace("\\", "/")
            if rel == "notes" or rel.startswith(notes_prefix):
                continue
            arcname = PROFILE_ZIP_VAULT_PREFIX + rel
            try:
                zf.write(abspath, arcname)
            except OSError:
                continue


def _import_vault_from_zip(base_dir: str, zf: zipfile.ZipFile) -> None:
    """Extract vault/* from bundle into SafeVault (skips notes/)."""
    vault = prefs.vault_path(base_dir)
    vault_abs = os.path.abspath(vault)
    os.makedirs(vault_abs, exist_ok=True)
    prefix = PROFILE_ZIP_VAULT_PREFIX
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir():
            continue
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix) :].lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        if rel == "notes" or rel.startswith("notes/"):
            continue
        dest = os.path.normpath(os.path.join(vault_abs, *rel.split("/")))
        dest_abs = os.path.abspath(dest)
        if dest_abs != vault_abs and not dest_abs.startswith(vault_abs + os.sep):
            continue
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            with zf.open(info, "r") as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        except OSError:
            continue


def _add_browser_data_to_zip(zf: zipfile.ZipFile, base_dir: str) -> None:
    """Append WebEngine profile dir as BrowserData/... (can be very large)."""
    bd = app_paths.browser_data_path(base_dir)
    if not os.path.isdir(bd):
        return
    prefix = PROFILE_ZIP_BROWSER_PREFIX
    for root, _, files in os.walk(bd):
        for fn in files:
            abspath = os.path.join(root, fn)
            rel = os.path.relpath(abspath, bd).replace("\\", "/")
            if not rel or ".." in rel.split("/"):
                continue
            arcname = prefix + rel
            try:
                zf.write(abspath, arcname)
            except OSError:
                continue


def _zip_contains_browser_data(zf: zipfile.ZipFile) -> bool:
    pfx = PROFILE_ZIP_BROWSER_PREFIX
    for n in zf.namelist():
        n = n.replace("\\", "/")
        if n.endswith("/"):
            continue
        if n.startswith(pfx) and n != pfx:
            return True
    return False


def _import_browser_data_from_zip(base_dir: str, zf: zipfile.ZipFile) -> bool:
    """Replace profile BrowserData/ from zip tree BrowserData/. Returns True if any file was restored."""
    if not _zip_contains_browser_data(zf):
        return False
    bd = app_paths.browser_data_path(base_dir)
    bd_abs = os.path.abspath(bd)
    if os.path.isdir(bd_abs):
        for name in os.listdir(bd_abs):
            path = os.path.join(bd_abs, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
    else:
        os.makedirs(bd_abs, exist_ok=True)

    prefix = PROFILE_ZIP_BROWSER_PREFIX
    wrote = False
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir():
            continue
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix) :].lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        dest = os.path.normpath(os.path.join(bd_abs, *rel.split("/")))
        dest_abs = os.path.abspath(dest)
        if dest_abs != bd_abs and not dest_abs.startswith(bd_abs + os.sep):
            continue
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            with zf.open(info, "r") as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            wrote = True
        except OSError:
            continue
    return wrote


def export_profile_to_zip(base_dir: str, zip_path: str, *, include_browser_data: bool = False) -> bool:
    """
    Write profile backup as ZIP: profile.json (structured data, no inlined vault blobs)
    + vault/ tree (all SafeVault files except notes/).
    Optionally + BrowserData/ (WebEngine: cache, localStorage, extension state, etc.).
    """
    try:
        payload = export_profile_payload(base_dir, inline_vault_files=False)
        payload["backup_format_version"] = 3
        payload["backup_bundle"] = "zip"
        payload["backup_includes_browser_data"] = bool(include_browser_data)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                PROFILE_ZIP_JSON_MEMBER,
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            _add_vault_tree_to_zip(zf, base_dir)
            if include_browser_data:
                _add_browser_data_to_zip(zf, base_dir)
        return True
    except OSError:
        return False


def import_profile_from_path(base_dir: str, file_path: str) -> bool:
    """Import from .zip (profile.json + vault/) or legacy .json file."""
    if not file_path or not os.path.isfile(file_path):
        return False
    lower = file_path.lower()
    if lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                try:
                    raw = zf.read(PROFILE_ZIP_JSON_MEMBER)
                except KeyError:
                    return False
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    return False
                return import_profile_payload(base_dir, payload, vault_zip=zf, import_browser_data=True)
        except (json.JSONDecodeError, OSError, zipfile.BadZipFile):
            return False
    payload = read_json(file_path, None)
    return import_profile_payload(base_dir, payload)


def _clear_notes_directory(notes_dir: str) -> None:
    if not os.path.isdir(notes_dir):
        return
    for name in os.listdir(notes_dir):
        path = os.path.join(notes_dir, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def export_profile_payload(base_dir: str, *, inline_vault_files: bool = True):
    from litebrowser.services import (
        download_mgr,
        extension_bridge,
        life_service,
        personal_service,
    )

    notes = []
    for note in personal_service.list_notes(base_dir):
        notes.append({"id": note["id"], "title": note["title"], "content": note.get("content", "")})
    payload = {
        "version": 1,
        "backup_format_version": 2,
        "exported_at": int(time.time()),
        "profile_meta": prefs.load_profile_meta(base_dir),
        "prefs": prefs.load_prefs(base_dir),
        "history_entries": prefs.load_history_entries(base_dir),
        "bookmarks": prefs.load_bookmarks(base_dir),
        "session": prefs.session_load(base_dir),
        "session_state": prefs.session_state_load(base_dir),
        "workspaces": workspace_manager.load(base_dir),
        "permissions": prefs.load_permissions(base_dir),
        "downloads": download_mgr.load_list(base_dir),
        "tab_sets": tab_sets.load_tab_sets(base_dir),
        "tasks": life_service.load_tasks(base_dir),
        "calendar": life_service.load_events(base_dir),
        "boards": life_service.load_boards(base_dir),
        "saved_pages": life_service.load_saved_pages(base_dir),
        "sync_state": life_service.load_sync_state(base_dir),
        "sync_account": life_service.load_sync_account(base_dir),
        "ai_settings": prefs.load_ai_settings(base_dir),
        "ai_index": read_json(prefs.ai_index_path(base_dir), {"version": 1, "built_at": 0, "docs": []}),
        "activity_history": load_activity(base_dir),
        "notes": notes,
        "extension_imports": read_json(
            extension_bridge.storage_path(base_dir),
            {"version": 1, "batches": []},
        ),
        "vault_files": _export_vault_files_excluding_notes(base_dir) if inline_vault_files else [],
    }
    return payload


def import_profile_payload(
    base_dir: str,
    payload: dict,
    vault_zip: zipfile.ZipFile | None = None,
    *,
    import_browser_data: bool = False,
):
    from litebrowser.services import (
        download_mgr,
        extension_bridge,
        life_service,
        personal_service,
    )

    if not isinstance(payload, dict):
        return False
    with profile_locked(base_dir):
        prefs.ensure_profile_layout(base_dir)
        prefs.save_prefs(base_dir, payload.get("prefs", {}))
        write_json(prefs.profile_meta_path(base_dir), payload.get("profile_meta", {}))
        prefs.save_history_entries(base_dir, payload.get("history_entries", []))
        prefs.save_bookmarks(base_dir, payload.get("bookmarks", []))
        prefs.session_save(base_dir, payload.get("session", []))
        session_state = payload.get("session_state")
        if isinstance(session_state, dict):
            prefs.session_state_save(base_dir, session_state)
        prefs.save_workspaces(
            base_dir,
            payload.get(
                "workspaces",
                {
                    "workspaces": [
                        {"id": "ws1", "name": "Workspace 1"},
                        {"id": "ws2", "name": "Workspace 2"},
                    ],
                    "current_id": "ws1",
                },
            ),
        )
        workspace_manager.ensure_dual_workspaces(base_dir)
        prefs.save_permissions(base_dir, payload.get("permissions", {}))
        download_mgr.save_list(base_dir, payload.get("downloads", []))
        tab_sets.save_tab_sets(base_dir, payload.get("tab_sets", {"version": 1, "sets": []}))
        ext = payload.get("extension_imports")
        if ext is not None:
            if isinstance(ext, dict):
                batches = ext.get("batches")
                if isinstance(batches, list):
                    extension_bridge.save_batches(base_dir, batches)
            elif isinstance(ext, list):
                extension_bridge.save_batches(base_dir, ext)
        life_service.save_tasks(base_dir, payload.get("tasks", []))
        life_service.save_events(base_dir, payload.get("calendar", []))
        life_service.save_boards(base_dir, payload.get("boards", []))
        life_service.save_saved_pages(base_dir, payload.get("saved_pages", []))
        life_service.save_sync_state(base_dir, payload.get("sync_state", {}))
        sync_account = payload.get("sync_account", {})
        write_json(life_service.sync_account_path(base_dir), sync_account if isinstance(sync_account, dict) else {})
        prefs.save_ai_settings(base_dir, payload.get("ai_settings", {}))
        write_json(prefs.ai_index_path(base_dir), payload.get("ai_index", {"version": 1, "built_at": 0, "docs": []}))
        save_activity(base_dir, payload.get("activity_history", {"version": 1, "events": []}))

        if vault_zip is not None:
            _import_vault_from_zip(base_dir, vault_zip)
            if import_browser_data:
                _import_browser_data_from_zip(base_dir, vault_zip)
        else:
            _import_vault_files(base_dir, payload.get("vault_files", []))

        notes_dir = personal_service.notes_dir(base_dir)
        # Validate every note path BEFORE clearing anything: a crafted backup
        # with "../" ids must never escape the notes dir (v6.4 allowed an
        # arbitrary-file-write via note_id), and a single bad entry must not
        # leave the vault wiped.
        valid_notes = []
        notes_root = os.path.abspath(notes_dir)
        for note in payload.get("notes", []):
            note_id = str(note.get("id", "") or "")
            if not note_id:
                continue
            candidate = os.path.abspath(os.path.join(notes_root, note_id.replace("/", os.sep)))
            if not candidate.startswith(notes_root + os.sep):
                continue
            valid_notes.append((candidate, note.get("content", "")))
        _clear_notes_directory(notes_dir)
        for path, content in valid_notes:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            try:
                write_text_atomic(path, content)
            except OSError:
                continue
        return True
