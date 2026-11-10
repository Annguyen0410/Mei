"""Persistent sync-conflict archive and resolution history.

Folder sync already keeps both copies for most stores, but the losing side was
only represented in an in-memory change report.  Once the dialog closed, the
other version could be gone.  This service stores both full versions (locally,
not in logs), deduplicates identical conflicts across repeated syncs, and keeps
an audit trail of every resolution.

Stored rows are user data and stay inside the profile.  Diagnostic reports only
name the store and a hashed record reference.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field

from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_health import read_json_checked
from litebrowser.core.storage_utils import write_json

_log = get_logger("conflict_service")

STORE_RELPATH = os.path.join("Recovery", "conflicts.json")
STORE_VERSION = 1
MAX_CONFLICTS = 500
MAX_HISTORY = 500
PENDING = "pending"
DEFERRED = "deferred"
RESOLVED = "resolved"
ACTIONS = ("keep_local", "keep_remote", "keep_both", "defer")


class ConflictError(OSError):
    """A conflict could not be archived or resolved safely."""


@dataclass
class ConflictResult:
    ok: bool
    status: str
    conflict: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "conflict": self.conflict,
            "error": self.error,
        }


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, STORE_RELPATH)


def _empty() -> dict:
    return {"version": STORE_VERSION, "conflicts": [], "history": []}


def _load(base_dir: str) -> dict:
    result = read_json_checked(_path(base_dir), dict)
    if result.status == "missing":
        return _empty()
    if not result.ok:
        raise ConflictError(
            f"the conflict archive is unreadable ({result.status}); its bytes were left untouched"
        )
    data = result.value
    conflicts = data.get("conflicts")
    history = data.get("history")
    return {
        "version": STORE_VERSION,
        "conflicts": [row for row in conflicts if isinstance(row, dict)]
        if isinstance(conflicts, list)
        else [],
        "history": [row for row in history if isinstance(row, dict)]
        if isinstance(history, list)
        else [],
    }


def _save(base_dir: str, data: dict) -> None:
    conflicts = data.get("conflicts") or []
    pending = [row for row in conflicts if row.get("status") != RESOLVED]
    resolved = [row for row in conflicts if row.get("status") == RESOLVED]
    # Never drop an unresolved conflict just because many arrived; prune only
    # the oldest resolved entries after the cap.
    if len(conflicts) > MAX_CONFLICTS:
        keep_resolved = max(0, MAX_CONFLICTS - len(pending))
        conflicts = pending + resolved[-keep_resolved:] if keep_resolved else pending
    payload = {
        "version": STORE_VERSION,
        "updated_at": int(time.time()),
        "conflicts": conflicts[-MAX_CONFLICTS:],
        "history": (data.get("history") or [])[-MAX_HISTORY:],
    }
    write_json(_path(base_dir), payload)


def _sha(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _signature(store: str, record_id: str, local, remote) -> str:
    return hashlib.sha256(
        f"{store}|{record_id}|{_sha(local)}|{_sha(remote)}".encode("utf-8", "surrogatepass")
    ).hexdigest()


def _title(store: str, local, remote, record_id: str) -> str:
    for row in (remote, local):
        if isinstance(row, dict):
            for key in ("title", "front", "name", "label", "url"):
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:160]
    return str(record_id)[:160] or store


def record_conflict(
    base_dir: str,
    *,
    store: str,
    record_id: str,
    local,
    remote,
    conflict_type: str = "both_edited",
    source_device: str = "",
) -> dict:
    """Archive both versions once per unique pair of hashes."""
    store = str(store or "").strip()[:80]
    record_id = str(record_id or "").strip()[:512]
    if not store or not record_id:
        return {}
    signature = _signature(store, record_id, local, remote)
    with profile_locked(base_dir):
        data = _load(base_dir)
        for row in data["conflicts"]:
            if row.get("signature") == signature:
                return copy.deepcopy(row)
        entry = {
            "id": uuid.uuid4().hex,
            "signature": signature,
            "created_at": int(time.time()),
            "store": store,
            "record_id": record_id,
            "title": _title(store, local, remote, record_id),
            "conflict_type": str(conflict_type or "both_edited")[:64],
            "source_device": str(source_device or "")[:128],
            "local": copy.deepcopy(local) if isinstance(local, dict) else {},
            "remote": copy.deepcopy(remote) if isinstance(remote, dict) else {},
            "local_sha256": _sha(local),
            "remote_sha256": _sha(remote),
            "status": PENDING,
            "resolution": {},
        }
        data["conflicts"].append(entry)
        _save(base_dir, data)
    _log.info("archived sync conflict in %s (%s)", store, entry["id"])
    return copy.deepcopy(entry)


def list_conflicts(base_dir: str, status: str | None = None) -> list[dict]:
    data = _load(base_dir)
    rows = data["conflicts"]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    return copy.deepcopy(sorted(rows, key=lambda row: int(row.get("created_at") or 0), reverse=True))


def history(base_dir: str) -> list[dict]:
    return copy.deepcopy(_load(base_dir)["history"])


def _apply_remote(base_dir: str, conflict: dict, *, keep_both: bool) -> str:
    from litebrowser.services import sync_folder

    adapter = sync_folder.ADAPTERS_BY_KEY.get(str(conflict.get("store") or ""))
    if adapter is None:
        raise ConflictError("This store cannot be resolved automatically.")
    remote = conflict.get("remote") if isinstance(conflict.get("remote"), dict) else {}
    if not remote:
        raise ConflictError("The archived remote version is empty.")
    record_id = str(conflict.get("record_id") or "")
    remote = copy.deepcopy(remote)
    remote["id"] = record_id
    if keep_both:
        if adapter.duplicate is None:
            raise ConflictError("This store cannot keep both versions automatically.")
        created = adapter.duplicate(base_dir, remote)
        if not created:
            raise ConflictError("The other version could not be added as a separate record.")
        return _sha(created)
    rows = adapter.load(base_dir)
    merged = [row for row in rows if str(row.get("id")) != record_id]
    merged.append(remote)
    adapter.replace(base_dir, merged)
    current = next(
        (row for row in adapter.load(base_dir) if str(row.get("id")) == record_id),
        remote,
    )
    return _sha(current)


def resolve_conflict(
    base_dir: str,
    conflict_id: str,
    action: str,
    *,
    confirm: bool = False,
) -> ConflictResult:
    """Resolve one archived conflict; both versions remain in history."""
    if not confirm:
        return ConflictResult(False, "confirmation_required", error="Explicit confirmation is required.")
    if action not in ACTIONS:
        return ConflictResult(False, "invalid_action", error="Unknown conflict action.")
    with profile_locked(base_dir):
        data = _load(base_dir)
        conflict = next((row for row in data["conflicts"] if row.get("id") == conflict_id), None)
        if conflict is None:
            return ConflictResult(False, "missing", error="Conflict not found.")
        if conflict.get("status") == RESOLVED and action != "defer":
            return ConflictResult(False, "already_resolved", conflict=copy.deepcopy(conflict))
        result_sha = ""
        try:
            if action == "keep_remote":
                result_sha = _apply_remote(base_dir, conflict, keep_both=False)
            elif action == "keep_both":
                result_sha = _apply_remote(base_dir, conflict, keep_both=True)
            elif action == "keep_local":
                result_sha = str(conflict.get("local_sha256") or "")
        except (ConflictError, OSError, ValueError) as exc:
            return ConflictResult(False, "failed", conflict=copy.deepcopy(conflict), error=str(exc))
        status = DEFERRED if action == "defer" else RESOLVED
        conflict["status"] = status
        conflict["resolution"] = {
            "action": action,
            "at": int(time.time()),
            "result_sha256": result_sha,
            "previous_local_sha256": conflict.get("local_sha256", ""),
            "previous_remote_sha256": conflict.get("remote_sha256", ""),
            "source_device": conflict.get("source_device", ""),
        }
        data["history"].append(
            {
                "conflict_id": conflict_id,
                "store": conflict.get("store", ""),
                "action": action,
                "at": int(time.time()),
                "result_sha256": result_sha,
                "device": conflict.get("source_device", ""),
            }
        )
        _save(base_dir, data)
        return ConflictResult(True, status, conflict=copy.deepcopy(conflict))


def _archive_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("conflicts")
    return [copy.deepcopy(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def merge_payload(current: dict | None, incoming: dict | None) -> tuple[dict, int]:
    """Merge a restored conflict archive without activating either version.

    The signature is derived from the two record versions, so restoring the
    same backup twice is idempotent.  Existing rows win (they may already have
    a resolution); a new incoming row with a colliding id but a different
    signature gets a fresh id instead of overwriting history.
    """
    base = _empty()
    existing = _archive_rows(current or {})
    incoming_rows = _archive_rows(incoming or {})
    signatures = {str(row.get("signature") or "") for row in existing}
    ids = {str(row.get("id") or "") for row in existing}
    added = 0
    for row in incoming_rows:
        signature = str(row.get("signature") or "")
        if not signature:
            signature = _signature(
                str(row.get("store") or ""),
                str(row.get("record_id") or ""),
                row.get("local"),
                row.get("remote"),
            )
        if signature in signatures:
            continue
        row["signature"] = signature
        if not row.get("id") or str(row.get("id")) in ids:
            row["id"] = uuid.uuid4().hex
        ids.add(str(row["id"]))
        signatures.add(signature)
        row.setdefault("status", PENDING)
        row.setdefault("created_at", int(time.time()))
        row.setdefault("resolution", {})
        existing.append(row)
        added += 1
    history = []
    seen_history = set()
    for row in (current or {}).get("history", []) if isinstance(current or {}, dict) else []:
        if not isinstance(row, dict):
            continue
        key = (row.get("conflict_id"), row.get("action"), row.get("at"))
        if key not in seen_history:
            seen_history.add(key)
            history.append(copy.deepcopy(row))
    for row in (incoming or {}).get("history", []) if isinstance(incoming or {}, dict) else []:
        if not isinstance(row, dict):
            continue
        key = (row.get("conflict_id"), row.get("action"), row.get("at"))
        if key not in seen_history:
            seen_history.add(key)
            history.append(copy.deepcopy(row))
    base["conflicts"] = existing[-MAX_CONFLICTS:]
    base["history"] = history[-MAX_HISTORY:]
    # An idempotent import must produce byte-identical content when it adds
    # nothing; otherwise restoring the same backup twice looks like a change.
    base["updated_at"] = (
        int(time.time())
        if added or not isinstance(current, dict) or not current.get("updated_at")
        else int(current.get("updated_at") or 0)
    )
    return base, added


def import_archive(base_dir: str, incoming: dict | None) -> dict:
    """Merge a conflict archive from a backup into the live archive."""
    if not isinstance(incoming, dict) or not isinstance(incoming.get("conflicts"), list):
        raise ConflictError("The conflict archive in this backup is not valid.")
    with profile_locked(base_dir):
        current = _load(base_dir)
        merged, added = merge_payload(current, incoming)
        _save(base_dir, merged)
    return {"added": added, "total": len(merged["conflicts"])}


def status(base_dir: str) -> dict:
    try:
        rows = list_conflicts(base_dir)
    except ConflictError as exc:
        return {"status": "unreadable", "pending": 0, "deferred": 0, "resolved": 0, "error": str(exc)}
    return {
        "status": "ok",
        "pending": sum(1 for row in rows if row.get("status") == PENDING),
        "deferred": sum(1 for row in rows if row.get("status") == DEFERRED),
        "resolved": sum(1 for row in rows if row.get("status") == RESOLVED),
        "total": len(rows),
    }


__all__ = [
    "ACTIONS",
    "ConflictError",
    "ConflictResult",
    "DEFERRED",
    "PENDING",
    "RESOLVED",
    "STORE_RELPATH",
    "history",
    "import_archive",
    "list_conflicts",
    "merge_payload",
    "record_conflict",
    "resolve_conflict",
    "status",
]
