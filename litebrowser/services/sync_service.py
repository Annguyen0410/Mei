"""Self-hosted sync — push/pull a profile snapshot to your own HTTP endpoint.

The endpoint is a tiny API you run yourself (see README "Self-hosted sync"):
POST /api/sync/push stores the latest snapshot, GET /api/sync/latest returns
it. Every request carries a Bearer token. The payload is one JSON bundle
containing the local data (tasks, events, boards, saved pages, notes,
bookmarks, history, the weekly planner, flashcards and entity links) so two
machines can stay in step without any cloud.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import threading
import urllib.error
import urllib.parse
from datetime import datetime
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from litebrowser.core import prefs, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_transaction
from litebrowser.core.storage_utils import write_json
from litebrowser.services import (
    conflict_service,
    flashcard_service,
    life_service,
    link_service,
    personal_plan,
    personal_service,
)

SYNC_API_VERSION = 1

_log = get_logger("sync_service")

#: The push gate is stored twice: in sync_state.json for the UI and in this
#: independent operation journal so damage to one file cannot open the gate.
SYNC_JOURNAL_RELPATH = os.path.join("Recovery", "sync_operation_journal.json")
SYNC_STAGING_RELPATH = os.path.join("Recovery", "sync_staging")
SYNC_JOURNAL_VERSION = 1

JOURNAL_CLEAN = "CLEAN"
JOURNAL_PREPARING_PULL = "PREPARING_PULL"
JOURNAL_FETCHED = "FETCHED"
JOURNAL_APPLYING = "APPLYING"
JOURNAL_ARCHIVE_PENDING = "ARCHIVE_PENDING"
JOURNAL_PUSH_BLOCKED = "PUSH_BLOCKED"
JOURNAL_APPLIED = "APPLIED"
JOURNAL_BASELINE_COMMITTED = "BASELINE_COMMITTED"
JOURNAL_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

SYNC_JOURNAL_STATES = frozenset(
    {
        JOURNAL_CLEAN,
        JOURNAL_PREPARING_PULL,
        JOURNAL_FETCHED,
        JOURNAL_APPLYING,
        JOURNAL_ARCHIVE_PENDING,
        JOURNAL_PUSH_BLOCKED,
        JOURNAL_APPLIED,
        JOURNAL_BASELINE_COMMITTED,
        JOURNAL_RECOVERY_REQUIRED,
    }
)
#: Only a clean (nothing applied) or a verified baseline commit opens the gate.
SYNC_JOURNAL_RESOLVED = frozenset({JOURNAL_CLEAN, JOURNAL_BASELINE_COMMITTED})

PULL_SUCCESS = "SUCCESS"
PULL_NO_REMOTE_SNAPSHOT = "NO_REMOTE_SNAPSHOT"
PULL_NETWORK_ERROR = "NETWORK_ERROR"
PULL_AUTH_ERROR = "AUTH_ERROR"
PULL_ENDPOINT_INVALID = "ENDPOINT_INVALID"
PULL_INVALID_BUNDLE = "INVALID_BUNDLE"
PULL_ARCHIVE_FAILED = "ARCHIVE_FAILED"
PULL_WRITE_FAILED = "WRITE_FAILED"
PULL_BASELINE_FAILED = "BASELINE_FAILED"
PULL_JOURNAL_FAILED = "JOURNAL_FAILED"
PULL_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

#: Process-local fail-closed latch.  If neither the journal nor sync_state can
#: be written, this session still refuses every push until restart.
_FAIL_CLOSED: set[str] = set()
_FAIL_CLOSED_LOCK = threading.Lock()


class _NoRemoteSnapshot(str):
    """A typed HTTP 404 marker, never recognised by matching ordinary text."""


class _AuthFailure(str):
    """A typed HTTP 401/403 marker."""


_NO_REMOTE_SNAPSHOT = _NoRemoteSnapshot("No snapshot yet")

#: A snapshot is remote input. These caps are checked before anything is
#: applied, so an oversized or deeply nested body fails without touching the
#: local profile.
MAX_BUNDLE_ROWS = 20_000
MAX_BUNDLE_STRING = 4 * 1024 * 1024
MAX_BUNDLE_DEPTH = 24
MAX_BUNDLE_KEYS = 256


@dataclass(frozen=True)
class SyncEntity:
    """One syncable collection: how to publish it and how to merge it back.

    Both directions read this registry, so adding an entity (or a new store) is
    one entry here instead of edits in three places — the bundle, the merge and
    the applied-count report used to drift apart.
    """

    key: str  # key inside the bundle payload
    counter: str  # key in the "applied" report shown to the user
    build: Callable[[str], Any]  # local profile -> bundle value
    merge: Callable[[str, Any], int]  # (profile, remote value) -> rows applied


class SyncMergeError(RuntimeError):
    """A merge could not safely complete; the pull must not be reported as OK."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class BundleMergeResult:
    applied: dict[str, int]
    status: str
    error: str = ""
    failed_store: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.status in ("APPLIED", "UNCHANGED")


@dataclass(frozen=True)
class PullResult:
    """A typed pull outcome; callers never infer safety from message text."""

    ok: bool
    status: str
    message: str
    applied: dict[str, int] | None = None


def _rows_entity(key: str, counter: str, load, save) -> SyncEntity:
    """A row list merged by id, archiving both versions before a winner.

    The old merge was last-writer-wins with no durable record of the losing
    edit.  A remote snapshot still wins by timestamp, but a differing local
    version is archived first and a failure to archive means the local record
    is left alone rather than being silently replaced.
    """

    def build(base_dir: str):
        return load(base_dir) or []

    def merge(base_dir: str, incoming) -> int:
        rows = _dict_rows(incoming)
        existing = list(load(base_dir) or [])
        by_id = {
            str(row.get("id")): index
            for index, row in enumerate(existing)
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
        }
        applied = 0
        changed = False
        for row in rows:
            record_id = row.get("id")
            if not isinstance(record_id, str) or not record_id:
                continue
            index = by_id.get(record_id)
            if index is None:
                existing.append(row)
                by_id[record_id] = len(existing) - 1
                changed = True
                applied += 1
                continue
            local = existing[index]
            if _row_fingerprint(local) == _row_fingerprint(row):
                continue
            if not _archive_http_conflict(base_dir, key, record_id, local, row):
                raise SyncMergeError(
                    "ARCHIVE_FAILED",
                    f"Could not preserve the {key} conflict for {record_id}; the local row was kept.",
                )
            if _timestamp(row) >= _timestamp(local):
                existing[index] = row
                changed = True
            applied += 1
        if changed:
            save(base_dir, existing)
        # Keep the historical "rows examined" counter: callers use it for the
        # report, including a malformed row that the store normaliser drops.
        return len(rows)

    return SyncEntity(key, counter, build, merge)


def _row_fingerprint(row) -> str:
    """Compare user content, not the volatile timestamp a save stamps."""
    if not isinstance(row, dict):
        return ""
    normalized = {
        str(key): value
        for key, value in row.items()
        if key not in ("updated_at", "created_at")
    }
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)


def _archive_http_conflict(base_dir: str, store: str, record_id: str, local, remote) -> bool:
    try:
        entry = conflict_service.record_conflict(
            base_dir,
            store=store,
            record_id=record_id,
            local=local,
            remote=remote,
            conflict_type="http_sync",
            source_device="remote snapshot",
        )
        return bool(entry)
    except (conflict_service.ConflictError, OSError, ValueError) as exc:
        # Keep local data if the archive cannot be written.  A failed archive
        # must never become a silent overwrite.
        from litebrowser.core.log import get_logger

        get_logger("sync_service").warning("could not archive HTTP conflict: %s", exc)
        return False


def _note_key(note_id) -> str:
    """Sync ids always use ``/``; local Windows ids use ``\\``."""
    return str(note_id or "").replace("\\", "/").strip("/")


def _note_identity(note: dict) -> tuple[str, str]:
    return (_text(note.get("title")), _text(note.get("category"), "General") or "General")


def _conflict_note(base_dir: str, title: str, category: str, content: str, known: list[dict]):
    """Keep the other device's differing text as a clearly named note once.

    The check is against the whole local list (including notes created earlier
    in this merge), so pulling the same unchanged remote snapshot repeatedly
    cannot grow a new conflict copy every time.
    """
    conflict_title = f"{title} (other device)"
    for note in known:
        if (
            _text(note.get("title")) == conflict_title
            and (_text(note.get("category"), "General") or "General") == category
            and (note.get("content") or "") == content
        ):
            return note
    created = personal_service.create_note(base_dir, conflict_title, content, category)
    if created:
        known.append(created)
    return created


def _merge_notes(base_dir: str, incoming) -> int:
    """Merge notes by stable id, with a non-destructive legacy fallback.

    The bundle has always carried a note ``id``, but this merge used to ignore
    it and match on ``(title, category)``. A rename therefore looked like a new
    note and two distinct notes that happened to share a title could collapse
    into one. Current-format records now merge by id: an edit updates the same
    note, a rename survives, and a genuinely divergent edit is preserved as a
    ``(other device)`` copy. Records from an older peer that lack an id keep the
    old title/category fallback, which only ever adds or preserves text.
    """
    applied = 0
    local_notes = [
        note for note in personal_service.list_notes(base_dir) if isinstance(note, dict) and note.get("id")
    ]
    by_id = {_note_key(note["id"]): note for note in local_notes}
    by_title: dict[tuple[str, str], dict] = {}
    for note in local_notes:
        by_title.setdefault(_note_identity(note), note)

    for note in _dict_rows(incoming):
        title = _text(note.get("title"))
        category = _text(note.get("category"), "General") or "General"
        content = note.get("content") if isinstance(note.get("content"), str) else ""
        note_id = _note_key(note.get("id"))

        if note_id and len(note_id) <= 512:
            existing = by_id.get(note_id)
            if existing is None:
                created = personal_service.create_note_with_id(base_dir, note_id, content)
                if created:
                    by_id[note_id] = created
                    by_title.setdefault(_note_identity(created), created)
                    local_notes.append(created)
                    applied += 1
                continue
            if (existing.get("content") or "") == content:
                continue
            if not _archive_http_conflict(base_dir, "notes", note_id, existing, note):
                raise SyncMergeError(
                    "ARCHIVE_FAILED",
                    f"Could not preserve the notes conflict for {note_id}; the local note was kept.",
                )
            remote_time = _timestamp(note)
            local_time = _timestamp(existing)
            if remote_time and (not local_time or remote_time > local_time):
                updated = personal_service.update_note(base_dir, existing["id"], content)
                if updated:
                    existing.clear()
                    existing.update(updated)
                    applied += 1
                continue
            _conflict_note(base_dir, title or _text(existing.get("title")) or "note", category, content, local_notes)
            applied += 1
            continue

        # Legacy peer: no id. Match by title/category only when the local note
        # is still in that location; otherwise a rename would be duplicated.
        if not title:
            continue
        existing = by_title.get((title, category))
        if existing:
            if (existing.get("content") or "") == content:
                continue
            if not _archive_http_conflict(
                base_dir,
                "notes",
                f"{title}/{category}",
                existing,
                note,
            ):
                raise SyncMergeError(
                    "ARCHIVE_FAILED",
                    f"Could not preserve the notes conflict for {title}/{category}.",
                )
            _conflict_note(base_dir, title, category, content, local_notes)
            applied += 1
            continue
        created = personal_service.create_note(base_dir, title, content, category)
        if created:
            by_id[_note_key(created["id"])] = created
            by_title[_note_identity(created)] = created
            local_notes.append(created)
            applied += 1
    return applied


def _merge_bookmarks(base_dir: str, incoming) -> int:
    """Merge by URL, archiving a differing remote version before keeping local.

    Bookmarks have no stable id in this store, so URL is the identity.  A
    divergent bookmark is never replaced automatically; both versions are
    archived and the local copy is kept.  This avoids losing a title/folder
    edit when two devices have edited the same URL.
    """
    remote_bookmarks = _dict_rows(incoming)
    if not remote_bookmarks:
        return 0
    local_bookmarks = prefs.load_bookmarks(base_dir) or []
    local_by_url = {}
    for bm in local_bookmarks:
        if isinstance(bm, dict):
            url = _text(bm.get("url"))
            if url:
                local_by_url[url] = bm
    merged = list(local_bookmarks)
    for bm in remote_bookmarks:
        url = _text(bm.get("url"))
        if not url:
            continue
        if url in local_by_url:
            local = local_by_url[url]
            if _row_fingerprint(local) != _row_fingerprint(bm):
                if not _archive_http_conflict(base_dir, "bookmarks", url, local, bm):
                    raise SyncMergeError(
                        "ARCHIVE_FAILED",
                        f"Could not preserve the bookmark conflict for {url}.",
                    )
            continue
        merged.append(bm)
        local_by_url[url] = bm
    if merged != local_bookmarks:
        prefs.save_bookmarks(base_dir, merged)
    return len(remote_bookmarks)


def _merge_history(base_dir: str, incoming) -> int:
    """Merge append-only (timestamp, url) entries, newest first.

    History is not a last-writer-wins record: two entries at the same second
    are both valid history.  No local entry is deleted or replaced, so this
    path has no destructive divergence to archive.  Duplicate exact tuples are
    ignored so repeated pulls stay idempotent.
    """
    remote_history = []
    items = incoming if isinstance(incoming, list) else []
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            remote_history.append((int(item[0] or 0), str(item[1] or "")))
        except (TypeError, ValueError, OverflowError):
            continue
    if not remote_history:
        return 0
    existing = prefs.load_history_entries(base_dir)
    merged = existing + [item for item in remote_history if item not in existing]
    merged.sort(key=lambda item: -int(item[0] or 0))
    # Keep a generous cap: v6.4 trimmed to 1500, so one pull from a sparse
    # device could throw away months of local history.
    prefs.save_history_entries(base_dir, merged[:5000])
    return len(remote_history)


def _build_notes(base_dir: str):
    return [
        {
            "id": n.get("id", ""),
            "updated_at": n.get("updated_at", ""),
            "title": n.get("title", ""),
            "category": n.get("category", "General"),
            "content": n.get("content", ""),
        }
        for n in (personal_service.list_notes(base_dir) or [])
    ]


def _merge_plan(base_dir: str, incoming) -> int:
    """Merge planner rows by id, archiving every divergent edit first.

    The planner is three collections in one file.  A conflict record uses the
    ``item:``/``course:``/``block:`` id shape the folder-sync adapter already
    understands, so both HTTP and folder conflicts can be resolved by the same
    service.  The semester header is only replaced when this profile has no
    local semester; otherwise a differing remote header is archived and the
    local one is kept rather than silently blanking user configuration.
    """
    if not isinstance(incoming, dict):
        return 0
    plan = personal_plan.load_plan(base_dir)
    applied = 0
    changed = False
    for key, kind in (("items", "item"), ("courses", "course"), ("time_blocks", "block")):
        rows = _dict_rows(incoming.get(key))
        current = _dict_rows(plan.get(key, []))
        by_id = {
            str(row.get("id")): index
            for index, row in enumerate(current)
            if isinstance(row.get("id"), str) and row.get("id")
        }
        for row in rows:
            record_id = row.get("id")
            if not isinstance(record_id, str) or not record_id:
                continue
            index = by_id.get(record_id)
            if index is None:
                current.append(row)
                by_id[record_id] = len(current) - 1
                changed = True
                applied += 1
                continue
            local = current[index]
            local_canonical = _canonical_plan_row(kind, local)
            remote_canonical = _canonical_plan_row(kind, row)
            if _row_fingerprint(local_canonical) == _row_fingerprint(remote_canonical):
                continue
            archive_local = dict(local_canonical, id=f"{kind}:{record_id}", _kind=kind)
            archive_remote = dict(remote_canonical, id=f"{kind}:{record_id}", _kind=kind)
            if not _archive_http_conflict(
                base_dir, "planner", f"{kind}:{record_id}", archive_local, archive_remote
            ):
                raise SyncMergeError(
                    "ARCHIVE_FAILED",
                    f"Could not preserve the planner conflict for {kind}:{record_id}.",
                )
            if _timestamp(row) > _timestamp(local):
                current[index] = row
                changed = True
            applied += 1
        plan[key] = current
    semester = incoming.get("semester")
    if isinstance(semester, dict) and any(_text(value) for value in semester.values()):
        local_semester = plan.get("semester") if isinstance(plan.get("semester"), dict) else {}
        if local_semester != semester:
            if not any(_text(value) for value in local_semester.values()):
                plan["semester"] = semester
                changed = True
            else:
                if not _archive_http_conflict(
                    base_dir, "planner", "semester", local_semester, semester
                ):
                    raise SyncMergeError(
                        "ARCHIVE_FAILED",
                        "Could not preserve the semester conflict; the local semester was kept.",
                    )
    if changed:
        personal_plan.save_plan(base_dir, plan)
    return applied


def _canonical_plan_row(kind: str, row: dict) -> dict:
    """Apply the planner's own normalizer before comparing or archiving.

    A sparse remote row and a locally normalized row otherwise look different
    only because the local writer filled optional fields.  That made the same
    conflict reappear on every pull.  The store normalizer is the single source
    of truth for what a planner record means.
    """
    normalizer = {
        "item": personal_plan._normalize_item,
        "course": personal_plan._normalize_course,
        "block": personal_plan._normalize_block,
    }[kind]
    normalized = normalizer(dict(row))
    return normalized if isinstance(normalized, dict) else dict(row)


# Bundle key, report key, publish, merge — in the order the report shows.
SYNC_ENTITIES: tuple[SyncEntity, ...] = (
    _rows_entity("tasks", "tasks", life_service.load_tasks, life_service.save_tasks),
    _rows_entity("events", "events", life_service.load_events, life_service.save_events),
    _rows_entity("boards", "boards", life_service.load_boards, life_service.save_boards),
    _rows_entity("saved_pages", "pages", life_service.load_saved_pages, life_service.save_saved_pages),
    SyncEntity("notes", "notes", _build_notes, _merge_notes),
    SyncEntity("bookmarks", "bookmarks", lambda b: prefs.load_bookmarks(b) or [], _merge_bookmarks),
    SyncEntity(
        "history",
        "history",
        lambda b: [list(item) for item in (prefs.load_history_entries(b) or [])[:500]],
        _merge_history,
    ),
    SyncEntity("personal_plan", "planner", personal_plan.load_plan, _merge_plan),
    _rows_entity(
        "flashcards", "flashcards", flashcard_service.load_cards, flashcard_service.save_cards
    ),
    _rows_entity("entity_links", "links", link_service.load_links, link_service.save_links),
)


@profile_transaction
def _bundle(base_dir: str) -> dict:
    payload = {
        "app": "litebrowser",
        "kind": "snapshot",
        "api": SYNC_API_VERSION,
        "exported_at": int(time.time()),
    }
    for entity in SYNC_ENTITIES:
        payload[entity.key] = entity.build(base_dir)
    return payload


def _dict_rows(value) -> list[dict]:
    """Return independently-owned mapping rows from an external snapshot.

    Sync responses are remote input.  A malformed array must be ignored rather
    than making a pull crash halfway through applying the rest of the bundle.
    """
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _text(value, default: str = "") -> str:
    """Accept text-only fields from a remote snapshot without coercion."""
    return value.strip() if isinstance(value, str) else default


def _upsert(existing, incoming, key="id"):
    existing_rows = _dict_rows(existing)
    incoming_rows = _dict_rows(incoming)
    by_id = {}
    unkeyed = []
    for item in existing_rows:
        row_id = item.get(key)
        if isinstance(row_id, str) and row_id:
            by_id[row_id] = item
        else:
            unkeyed.append(item)
    for item in incoming_rows:
        row_id = item.get(key)
        if not isinstance(row_id, str) or not row_id:
            continue
        current = by_id.get(row_id)
        if current is None or _timestamp(item) >= _timestamp(current):
            by_id[row_id] = item
    return [*unkeyed, *by_id.values()]


def _timestamp(row):
    value = row.get("updated_at") or row.get("created_at") or 0
    try:
        result = float(value)
        return result if math.isfinite(result) else 0
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (ValueError, OSError, OverflowError):
            return 0


@profile_transaction
def _apply_bundle_result(base_dir: str, bundle: dict) -> BundleMergeResult:
    """Merge a remote snapshot into the local profile (last-writer-wins per item).

    Each collection is merged by the rule in its ``SYNC_ENTITIES`` entry, so a
    new synced store only needs a registry entry — the bundle, the merge and the
    applied-count report can no longer drift apart.
    """
    applied = {entity.counter: 0 for entity in SYNC_ENTITIES}
    if not isinstance(bundle, dict):
        return BundleMergeResult(applied, "VALIDATION_FAILED", "Remote snapshot is not an object.")
    changed = False
    for entity in SYNC_ENTITIES:
        if entity.key in bundle:
            try:
                count = entity.merge(base_dir, bundle[entity.key])
            except SyncMergeError as exc:
                return BundleMergeResult(
                    applied, exc.status, str(exc), entity.counter
                )
            except (OSError, ValueError, TypeError) as exc:
                return BundleMergeResult(
                    applied,
                    "WRITE_FAILED",
                    f"Could not apply {entity.counter}: {exc}",
                    entity.counter,
                )
            applied[entity.counter] = count
            changed = changed or bool(count)
    return BundleMergeResult(applied, "APPLIED" if changed else "UNCHANGED")


def _apply_bundle(base_dir: str, bundle: dict) -> dict:
    """Apply a bundle or raise; failure is never returned as counts.

    The old wrapper dropped the failure status, so an archive/write failure
    looked exactly like a successful merge to every direct caller.  Safety
    callers use ``_apply_bundle_result``; this compatibility entry point now
    raises the same typed ``SyncMergeError`` instead of lying.
    """
    result = _apply_bundle_result(base_dir, bundle)
    if not result.ok:
        raise SyncMergeError(
            result.status,
            result.error or "The remote snapshot could not be applied safely.",
        )
    return result.applied


def validate_endpoint(endpoint: str) -> tuple[str, str]:
    """Return ``(base_url, error)`` for a user-entered sync endpoint.

    Only explicit http(s) base URLs are accepted. Credentials in the URL,
    query strings and fragments are refused before the bearer token is ever
    attached; a redirect is still blocked separately in ``_NoRedirect``.
    """
    text = str(endpoint or "").strip().rstrip("/")
    if not text:
        return "", "No sync endpoint set."
    try:
        parsed = urllib.parse.urlsplit(text)
        _ = parsed.port
    except ValueError:
        return "", "The sync endpoint is not a valid URL."
    if parsed.scheme not in ("http", "https"):
        return "", "The sync endpoint must start with http:// or https://."
    if not parsed.hostname:
        return "", "The sync endpoint has no host name."
    if parsed.username or parsed.password:
        return "", "Remove the username or password from the endpoint; the bearer token is the credential."
    if parsed.query or parsed.fragment:
        return "", "Enter the base endpoint only, without a query string or fragment."
    return text, ""


def endpoint_warning(endpoint: str) -> str:
    """A clear caution for a non-loopback cleartext endpoint, else ``""``.

    The bearer token travels with every request. HTTP on a LAN is a deliberate
    small-server choice, not something Mei should hide from the user.
    """
    base, error = validate_endpoint(endpoint)
    if error:
        return error
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "http":
        return ""
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if host == "localhost":
        return ""
    try:
        if ipaddress.ip_address(host).is_loopback:
            return ""
    except ValueError:
        pass
    return (
        "This endpoint uses cleartext HTTP, so the bearer token and your notes travel "
        "unencrypted on the network. Use HTTPS, or an HTTP endpoint only on a trusted "
        "local network or through a VPN."
    )


def _bundle_within_limits(value, depth: int = 0) -> bool:
    """Bound a remote snapshot before any store is touched."""
    if depth > MAX_BUNDLE_DEPTH:
        return False
    if isinstance(value, str):
        return len(value) <= MAX_BUNDLE_STRING
    if isinstance(value, dict):
        return len(value) <= MAX_BUNDLE_KEYS and all(
            isinstance(key, str) and len(key) <= 256 and _bundle_within_limits(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return len(value) <= MAX_BUNDLE_ROWS and all(
            _bundle_within_limits(item, depth + 1) for item in value
        )
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (bool, int))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A sync endpoint must not forward a profile/token to another host.
        return None


def _request(url: str, token: str, method: str = "GET", payload=None) -> tuple[bool, object, str]:
    try:
        headers = {
            "Authorization": "Bearer %s" % token,
            "X-Mei-Sync": "1",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=15) as resp:
            raw = resp.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024:
                return False, None, "Sync snapshot is too large"
            body = raw.decode("utf-8")
            parsed = None
            if body.strip():
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = body
            return True, parsed, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None, _NO_REMOTE_SNAPSHOT
        if exc.code in (401, 403):
            return False, None, _AuthFailure(str(exc))
        return False, None, str(exc)
    except (OSError, ValueError, UnicodeError) as exc:
        return False, None, str(exc)


def sync_journal_path(base_dir: str) -> str:
    return os.path.join(base_dir, SYNC_JOURNAL_RELPATH)


def _base_key(base_dir: str) -> str:
    return os.path.normcase(os.path.realpath(base_dir))


def _mark_fail_closed(base_dir: str) -> None:
    with _FAIL_CLOSED_LOCK:
        _FAIL_CLOSED.add(_base_key(base_dir))


def _is_fail_closed(base_dir: str) -> bool:
    with _FAIL_CLOSED_LOCK:
        return _base_key(base_dir) in _FAIL_CLOSED


def _clear_fail_closed(base_dir: str) -> None:
    with _FAIL_CLOSED_LOCK:
        _FAIL_CLOSED.discard(_base_key(base_dir))


def _load_sync_journal(base_dir: str) -> tuple[str, dict, str]:
    """Return ``(MISSING|OK|DAMAGED, journal, detail)`` without guessing."""
    result = storage_health.read_json_checked(sync_journal_path(base_dir), dict)
    if result.status == "missing":
        return "MISSING", {}, ""
    if not result.ok:
        return "DAMAGED", {}, result.detail or result.status
    journal = dict(result.value)
    if (
        journal.get("kind") != "mei.sync_journal"
        or journal.get("version") != SYNC_JOURNAL_VERSION
    ):
        return "DAMAGED", {}, "unrecognised sync safety journal"
    state = str(journal.get("state") or "")
    if state not in SYNC_JOURNAL_STATES:
        return "DAMAGED", journal, f"unknown sync safety state {state!r}"
    return "OK", journal, ""


def _new_sync_journal(endpoint: str) -> dict:
    now = int(time.time())
    return {
        "kind": "mei.sync_journal",
        "version": SYNC_JOURNAL_VERSION,
        "operation_id": uuid.uuid4().hex,
        "state": JOURNAL_PREPARING_PULL,
        "endpoint_sha256": hashlib.sha256(
            str(endpoint or "").encode("utf-8")
        ).hexdigest()[:16],
        "started_at": now,
        "updated_at": now,
        "finished_at": 0,
        "applied": {},
        "failed_store": "",
        "bundle_path": "",
        "bundle_sha256": "",
        "error": "",
        "outcome": "",
    }


def _write_sync_journal(base_dir: str, journal: dict) -> bool:
    journal["updated_at"] = int(time.time())
    try:
        write_json(sync_journal_path(base_dir), journal)
        return True
    except OSError as exc:
        _log.warning("could not persist the sync safety journal: %s", exc)
        return False


def _set_journal_state(base_dir: str, journal: dict, state: str, **fields) -> bool:
    journal["state"] = state
    for key, value in fields.items():
        journal[key] = value
    return _write_sync_journal(base_dir, journal)


def _stage_bundle(base_dir: str, journal: dict, bundle: dict) -> bool:
    """Persist the remote snapshot before any store is touched."""
    try:
        raw = json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return False
    path = os.path.join(
        base_dir, SYNC_STAGING_RELPATH, f"{journal.get('operation_id', '')}.json"
    )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, bundle)
    except OSError as exc:
        _log.warning("could not stage the remote sync snapshot: %s", exc)
        return False
    journal["bundle_path"] = os.path.relpath(path, base_dir).replace("\\", "/")
    journal["bundle_sha256"] = hashlib.sha256(raw).hexdigest()
    return True


def _remove_staged(base_dir: str, journal: dict) -> None:
    relative = str(journal.get("bundle_path") or "")
    if not relative:
        return
    candidate = os.path.normpath(os.path.join(base_dir, relative.replace("/", os.sep)))
    staging_root = os.path.normcase(
        os.path.realpath(os.path.join(base_dir, SYNC_STAGING_RELPATH))
    )
    try:
        if (
            os.path.normcase(os.path.realpath(os.path.dirname(candidate)))
            == staging_root
        ):
            os.remove(candidate)
    except OSError:
        pass


def _editable_sync_state(base_dir: str) -> dict:
    checked = life_service.load_sync_state_checked(base_dir)
    if not checked.ok:
        raise OSError(
            f"sync state is {checked.status.lower()}; refusing to rewrite it"
        )
    return dict(checked.value)


def _push_gate(base_dir: str) -> tuple[bool, str]:
    """The only push permission check; every caller goes through it."""
    if _is_fail_closed(base_dir):
        return (
            False,
            "Push blocked: this session could not persist its sync safety state.",
        )
    status, journal, detail = _load_sync_journal(base_dir)
    if status == "DAMAGED":
        return (
            False,
            "Push blocked: the sync safety journal is unreadable or invalid ("
            + (detail or "unknown")
            + "). Restore it or the profile from a verified backup.",
        )
    if status == "OK":
        state = str(journal.get("state") or "")
        if state not in SYNC_JOURNAL_RESOLVED:
            reason = str(
                journal.get("error") or "the previous sync did not finish safely"
            )
            return (
                False,
                f"Push blocked: sync safety state {state}. {reason} "
                "Retry a pull to reconcile, or restore the profile from a verified backup.",
            )
    checked = life_service.load_sync_state_checked(base_dir)
    if not checked.ok:
        return (
            False,
            f"Push blocked: sync state is {checked.status.lower()}; "
            "repair or restore sync_state.json before pushing.",
        )
    if checked.value.get("push_blocked"):
        return False, "Push blocked: a previous pull could not preserve a conflict. " + str(
            checked.value.get("push_blocked_reason") or "Resolve the conflict first."
        )
    return True, ""


def push(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    allowed, reason = _push_gate(base_dir)
    if not allowed:
        return False, reason
    endpoint, error = validate_endpoint(endpoint)
    if error:
        return False, error
    ok, _resp, err = _request(
        endpoint + "/api/sync/push", token, method="POST", payload=_bundle(base_dir)
    )
    if not ok:
        return False, "Push failed: %s" % (err or "connection error")
    _record_sync(base_dir, pushed_at=int(time.time()))
    return True, "Pushed snapshot."


def pull_typed(base_dir: str, endpoint: str, token: str) -> PullResult:
    """Pull with a durable safety journal and an explicit outcome type."""
    endpoint, error = validate_endpoint(endpoint)
    if error:
        return PullResult(False, PULL_ENDPOINT_INVALID, error)
    prior_status, prior, prior_detail = _load_sync_journal(base_dir)
    if prior_status == "DAMAGED":
        return PullResult(
            False,
            PULL_RECOVERY_REQUIRED,
            "Pull refused: the sync safety journal is unreadable or invalid; "
            "repair or restore it before syncing again. " + (prior_detail or ""),
        )
    prior_unresolved = prior_status == "OK" and str(
        prior.get("state") or ""
    ) not in SYNC_JOURNAL_RESOLVED
    journal = _new_sync_journal(endpoint)
    if prior_unresolved:
        # A retry must never erase the evidence of an earlier partial apply.
        journal["previous"] = {
            "operation_id": prior.get("operation_id", ""),
            "state": prior.get("state", ""),
            "error": prior.get("error", ""),
            "applied": prior.get("applied") or {},
            "failed_store": prior.get("failed_store", ""),
            "bundle_path": prior.get("bundle_path", ""),
        }
        journal["state"] = JOURNAL_RECOVERY_REQUIRED
        journal["error"] = "retrying after an unresolved sync operation"
    if not _write_sync_journal(base_dir, journal):
        _mark_fail_closed(base_dir)
        return PullResult(
            False,
            PULL_JOURNAL_FAILED,
            "Pull refused: the sync safety journal could not be written, so no remote data was applied.",
        )

    ok, resp, err = _request(endpoint + "/api/sync/latest", token)
    if not ok:
        if err is _NO_REMOTE_SNAPSHOT:
            if prior_unresolved:
                _set_journal_state(
                    base_dir,
                    journal,
                    JOURNAL_RECOVERY_REQUIRED,
                    outcome=PULL_NO_REMOTE_SNAPSHOT,
                    error="the server has no snapshot; the earlier unresolved sync still needs recovery",
                )
            else:
                _set_journal_state(
                    base_dir,
                    journal,
                    JOURNAL_CLEAN,
                    outcome=PULL_NO_REMOTE_SNAPSHOT,
                    finished_at=int(time.time()),
                )
            return PullResult(
                False,
                PULL_NO_REMOTE_SNAPSHOT,
                "Pull skipped: the server has no snapshot yet.",
            )
        status = PULL_AUTH_ERROR if isinstance(err, _AuthFailure) else PULL_NETWORK_ERROR
        message = "Pull failed: %s" % (err or "connection error")
        if prior_unresolved:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_RECOVERY_REQUIRED,
                outcome=status,
                error=message[:2000],
            )
        else:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_CLEAN,
                outcome=status,
                error=message[:2000],
                finished_at=int(time.time()),
            )
        return PullResult(False, status, message)

    if (
        not isinstance(resp, dict)
        or resp.get("kind") != "snapshot"
        or resp.get("api", 1) != SYNC_API_VERSION
        or resp.get("app", "litebrowser") not in ("litebrowser", "mei")
    ):
        message = "Remote did not return a snapshot."
        if prior_unresolved:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_RECOVERY_REQUIRED,
                outcome=PULL_INVALID_BUNDLE,
                error=message,
            )
        else:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_CLEAN,
                outcome=PULL_INVALID_BUNDLE,
                error=message,
                finished_at=int(time.time()),
            )
        return PullResult(False, PULL_INVALID_BUNDLE, message)
    if not _bundle_within_limits(resp):
        message = "Remote snapshot is malformed or too large. Nothing was changed."
        if prior_unresolved:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_RECOVERY_REQUIRED,
                outcome=PULL_INVALID_BUNDLE,
                error=message,
            )
        else:
            _set_journal_state(
                base_dir,
                journal,
                JOURNAL_CLEAN,
                outcome=PULL_INVALID_BUNDLE,
                error=message,
                finished_at=int(time.time()),
            )
        return PullResult(False, PULL_INVALID_BUNDLE, message)

    if not _stage_bundle(base_dir, journal, resp):
        message = (
            "Pull refused: the remote snapshot could not be staged safely, "
            "so no local store was changed."
        )
        _mark_fail_closed(base_dir)
        _set_journal_state(
            base_dir,
            journal,
            JOURNAL_RECOVERY_REQUIRED,
            outcome=PULL_JOURNAL_FAILED,
            error=message,
        )
        return PullResult(False, PULL_JOURNAL_FAILED, message)
    if not _set_journal_state(
        base_dir, journal, JOURNAL_FETCHED
    ) or not _set_journal_state(base_dir, journal, JOURNAL_APPLYING):
        _mark_fail_closed(base_dir)
        return PullResult(
            False,
            PULL_JOURNAL_FAILED,
            "Pull refused: the sync safety journal could not record the apply step, so no local store was changed.",
        )

    result = _apply_bundle_result(base_dir, resp)
    journal["applied"] = dict(result.applied)
    journal["failed_store"] = result.failed_store
    if not result.ok:
        message = result.error or "The remote snapshot could not be applied safely."
        state = (
            JOURNAL_ARCHIVE_PENDING
            if result.status == "ARCHIVE_FAILED"
            else JOURNAL_RECOVERY_REQUIRED
        )
        _block_push(base_dir, message, journal=journal, state=state)
        status = (
            PULL_ARCHIVE_FAILED
            if result.status == "ARCHIVE_FAILED"
            else PULL_WRITE_FAILED
        )
        return PullResult(False, status, "Pull blocked: " + message, result.applied)

    if not _set_journal_state(base_dir, journal, JOURNAL_APPLIED):
        _mark_fail_closed(base_dir)
        _block_push(
            base_dir,
            "the applied pull could not be recorded",
            journal=journal,
            state=JOURNAL_RECOVERY_REQUIRED,
        )
        return PullResult(
            False,
            PULL_RECOVERY_REQUIRED,
            "Pull applied local data but could not record it durably; push was blocked.",
            result.applied,
        )

    try:
        _record_sync(base_dir, pulled_at=int(time.time()))
        _clear_push_block(base_dir)
    except OSError as exc:
        reason = f"Could not record the pull baseline: {exc}"
        _block_push(base_dir, reason, journal=journal, state=JOURNAL_APPLIED)
        return PullResult(
            False,
            PULL_BASELINE_FAILED,
            "Pull applied local data but could not record its baseline; push was blocked. "
            + reason,
            result.applied,
        )

    if not _set_journal_state(
        base_dir,
        journal,
        JOURNAL_BASELINE_COMMITTED,
        outcome=PULL_SUCCESS,
        error="",
        finished_at=int(time.time()),
    ):
        _mark_fail_closed(base_dir)
        _block_push(
            base_dir,
            "the committed pull could not be recorded",
            journal=journal,
            state=JOURNAL_RECOVERY_REQUIRED,
        )
        return PullResult(
            False,
            PULL_BASELINE_FAILED,
            "Pull applied local data but its safety journal could not be committed; push was blocked.",
            result.applied,
        )
    _remove_staged(base_dir, journal)
    _clear_fail_closed(base_dir)
    applied = result.applied
    counts = " · ".join("%s=%s" % (k, v) for k, v in applied.items() if v)
    return PullResult(
        True,
        PULL_SUCCESS,
        "Pulled snapshot. (%s)" % (counts or "no changes"),
        applied,
    )


def pull(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    result = pull_typed(base_dir, endpoint, token)
    return result.ok, result.message


def sync_now(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    # Read before publishing: publishing first replaces the only remote copy
    # and silently discards changes from the other device.
    result = pull_typed(base_dir, endpoint, token)
    if not result.ok and result.status != PULL_NO_REMOTE_SNAPSHOT:
        return False, result.message
    ok_push, msg_push = push(base_dir, endpoint, token)
    if not ok_push:
        return False, msg_push
    return True, (result.message + " " + msg_push).strip()


@profile_transaction
def _record_sync(base_dir: str, pushed_at: int | None = None, pulled_at: int | None = None):
    data = _editable_sync_state(base_dir)
    if pushed_at:
        data["last_push_at"] = pushed_at
    if pulled_at:
        data["last_pull_at"] = pulled_at
    data["last_sync_at"] = int(time.time())
    life_service.save_sync_state(base_dir, data)


@profile_transaction
def _block_push(
    base_dir: str,
    reason: str,
    *,
    journal: dict | None = None,
    state: str = JOURNAL_PUSH_BLOCKED,
) -> bool:
    """Persist the block in two independent places and fail closed on error."""
    safe_reason = str(reason)[:2000]
    if journal is None:
        status, loaded, _detail = _load_sync_journal(base_dir)
        journal = loaded if status == "OK" else _new_sync_journal("")
    if not journal.get("operation_id"):
        journal["operation_id"] = uuid.uuid4().hex
    journal["state"] = state
    journal["error"] = safe_reason
    journal["push_blocked_at"] = int(time.time())
    journal_ok = _write_sync_journal(base_dir, journal)
    state_ok = False
    try:
        data = _editable_sync_state(base_dir)
        data["push_blocked"] = True
        data["push_blocked_reason"] = safe_reason
        data["push_blocked_at"] = int(time.time())
        life_service.save_sync_state(base_dir, data)
        state_ok = True
    except OSError as exc:
        _log.warning("could not persist the sync push block: %s", exc)
    journal["block_metadata"] = {"journal": journal_ok, "sync_state": state_ok}
    if journal_ok:
        _write_sync_journal(base_dir, journal)
    else:
        _mark_fail_closed(base_dir)
    # A partially persisted block is still safe (the surviving copy gates push)
    # but it must never be reported as fully recorded.
    return bool(journal_ok and state_ok)


@profile_transaction
def _clear_push_block(base_dir: str) -> None:
    data = _editable_sync_state(base_dir)
    if not data.get("push_blocked"):
        return
    data.pop("push_blocked", None)
    data.pop("push_blocked_reason", None)
    data.pop("push_blocked_at", None)
    life_service.save_sync_state(base_dir, data)


def last_sync(base_dir: str) -> int | None:
    checked = life_service.load_sync_state_checked(base_dir)
    if not checked.ok:
        return None
    value = int(checked.value.get("last_sync_at") or 0)
    return value or None
