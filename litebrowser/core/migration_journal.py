"""A small persistent journal for store migrations.

Mei's stepwise migration registry is deterministic, but the filesystem sequence
around it was not: read old payload → transform in memory → write new payload.
A crash after the write and before the caller persisted its own marker could
leave no record of what happened.

The journal is intentionally local and boring:

* one JSON file under ``<profile>/Recovery``;
* one entry per attempted store migration;
* a byte-for-byte snapshot of the source before any rewrite;
* explicit states, with ``RECOVERY_REQUIRED`` meaning "do not guess";
* :func:`reconcile` compares each unfinished entry with the store's *current*
  on-disk version, so a crash after replacement is recognised as committed and
  a crash before replacement is not replayed blindly.

It is not a distributed transaction manager and does not claim multi-file
atomicity.  Each store is tracked independently.
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass

from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_health import (
    RECOVERY_DIR,
    read_json_checked,
)
from litebrowser.core.storage_utils import _atomic_replace, write_json

_log = get_logger("migration_journal")

JOURNAL_RELPATH = os.path.join(RECOVERY_DIR, "migration_journal.json")
SNAPSHOT_DIR = os.path.join(RECOVERY_DIR, "migration_snapshots")
JOURNAL_VERSION = 1
MAX_ENTRIES = 200

PENDING = "PENDING"
PREPARING = "PREPARING"
BACKUP_CREATED = "BACKUP_CREATED"
APPLYING = "APPLYING"
VALIDATING = "VALIDATING"
COMMITTED = "COMMITTED"
FAILED = "FAILED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
ROLLED_BACK = "ROLLED_BACK"

ACTIVE_STATES = frozenset({PENDING, PREPARING, BACKUP_CREATED, APPLYING, VALIDATING})
TERMINAL_STATES = frozenset({COMMITTED, FAILED, ROLLED_BACK})


class MigrationJournalError(OSError):
    """The journal could not be read or written safely."""


@dataclass(frozen=True)
class RecoveryResult:
    journal_id: str
    store: str
    state: str
    action: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "journal_id": self.journal_id,
            "store": self.store,
            "state": self.state,
            "action": self.action,
            "detail": self.detail,
        }


def journal_path(base_dir: str) -> str:
    return os.path.join(base_dir, JOURNAL_RELPATH)


def _load(base_dir: str) -> dict:
    path = journal_path(base_dir)
    result = read_json_checked(path, dict)
    if result.status == "missing":
        return {"version": JOURNAL_VERSION, "entries": []}
    if not result.ok:
        raise MigrationJournalError(
            f"migration journal is unreadable ({result.status}: {result.detail})"
        )
    data = result.value
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise MigrationJournalError("migration journal has no entry list")
    return {"version": JOURNAL_VERSION, "entries": [e for e in entries if isinstance(e, dict)]}


def _save(base_dir: str, data: dict) -> None:
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise MigrationJournalError("refusing to write a journal without an entry list")
    payload = {
        "version": JOURNAL_VERSION,
        "updated_at": int(time.time()),
        "entries": entries[-MAX_ENTRIES:],
    }
    write_json(journal_path(base_dir), payload)


def _append(base_dir: str, entry: dict) -> None:
    with profile_locked(base_dir):
        data = _load(base_dir)
        data["entries"].append(entry)
        _save(base_dir, data)


def _update(base_dir: str, journal_id: str, **fields) -> dict:
    with profile_locked(base_dir):
        data = _load(base_dir)
        for entry in data["entries"]:
            if entry.get("id") != journal_id:
                continue
            entry.update(fields)
            entry["last_update"] = int(time.time())
            _save(base_dir, data)
            return dict(entry)
    raise MigrationJournalError(f"migration journal entry {journal_id} disappeared")


def snapshot_dir(base_dir: str) -> str:
    path = os.path.join(base_dir, SNAPSHOT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def create_snapshot(base_dir: str, store_path: str, store_name: str, source_version: int) -> tuple[str, str]:
    """Copy the source bytes before a rewrite. Returns (relative path, sha256)."""
    try:
        with open(store_path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise MigrationJournalError(f"could not snapshot {store_name}: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    safe_name = "".join(c if c.isalnum() or c in "._-" else "-" for c in store_name)[:48] or "store"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = f"{stamp}-{safe_name}-v{int(source_version)}-{digest[:12]}.snapshot"
    target = os.path.join(snapshot_dir(base_dir), name)
    if os.path.exists(target):
        name = f"{stamp}-{safe_name}-v{int(source_version)}-{digest[:12]}-{uuid.uuid4().hex[:6]}.snapshot"
        target = os.path.join(snapshot_dir(base_dir), name)
    temporary = target + ".part"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return os.path.relpath(target, base_dir), digest


def begin(
    base_dir: str,
    *,
    store_name: str,
    source_version: int,
    target_version: int,
    migration_version: int = 1,
) -> dict:
    """Open a journal entry before any snapshot or rewrite is attempted."""
    now = int(time.time())
    entry = {
        "id": uuid.uuid4().hex,
        "kind": "mei.store_migration",
        "store": str(store_name),
        "source_schema_version": int(source_version),
        "target_schema_version": int(target_version),
        "migration_implementation_version": int(migration_version),
        "started_at": now,
        "last_update": now,
        "completed_at": 0,
        "state": PENDING,
        "snapshot": "",
        "input_sha256": "",
        "output_sha256": "",
        "error": "",
        "recovery_action": "",
    }
    _append(base_dir, entry)
    return entry


def mark_backup_created(base_dir: str, journal_id: str, snapshot: str, input_sha256: str) -> dict:
    return _update(
        base_dir,
        journal_id,
        state=BACKUP_CREATED,
        snapshot=snapshot,
        input_sha256=input_sha256,
    )


def mark_applying(base_dir: str, journal_id: str) -> dict:
    return _update(base_dir, journal_id, state=APPLYING)


def mark_validating(base_dir: str, journal_id: str, output_sha256: str = "") -> dict:
    return _update(base_dir, journal_id, state=VALIDATING, output_sha256=output_sha256)


def mark_committed(base_dir: str, journal_id: str, output_sha256: str = "") -> dict:
    return _update(
        base_dir,
        journal_id,
        state=COMMITTED,
        output_sha256=output_sha256,
        completed_at=int(time.time()),
    )


def mark_failed(base_dir: str, journal_id: str, error: str, *, recovery_required: bool = False) -> dict:
    return _update(
        base_dir,
        journal_id,
        state=RECOVERY_REQUIRED if recovery_required else FAILED,
        error=str(error)[:2000],
        recovery_action=(
            "The original bytes are in the journal snapshot; the store was not rewritten."
            if recovery_required
            else ""
        ),
        completed_at=int(time.time()),
    )


def entries(base_dir: str) -> list[dict]:
    try:
        return _load(base_dir)["entries"]
    except MigrationJournalError as exc:
        _log.warning("cannot read migration journal: %s", exc)
        return []


def pending(base_dir: str) -> list[dict]:
    """Entries that still need reconciliation, including recovery-required ones.

    A crash after replacement but before the journal commit leaves the entry in
    ``RECOVERY_REQUIRED``; the next startup must compare it with the store again
    and close it as committed when the target version is already on disk.
    """
    return [
        entry
        for entry in entries(base_dir)
        if entry.get("state") in ACTIVE_STATES or entry.get("state") == RECOVERY_REQUIRED
    ]


def _current_store_version(base_dir: str, store_name: str) -> int | None:
    path = os.path.join(base_dir, store_name)
    result = read_json_checked(path, dict)
    if not result.ok:
        return None
    try:
        return int(result.value.get("version", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        return None


def reconcile(base_dir: str) -> list[RecoveryResult]:
    """Resolve unfinished entries against the store's actual version.

    * target version on disk → the replacement landed; mark COMMITTED.
    * older version on disk → the rewrite did not land; mark RECOVERY_REQUIRED
      and keep the snapshot.  Never re-run the migration automatically.
    * unreadable store → RECOVERY_REQUIRED with no guess.
    """
    results: list[RecoveryResult] = []
    for entry in pending(base_dir):
        journal_id = str(entry.get("id") or "")
        store_name = str(entry.get("store") or "")
        target = int(entry.get("target_schema_version") or 0)
        current = _current_store_version(base_dir, store_name)
        if current is not None and target and current >= target:
            _update(
                base_dir,
                journal_id,
                state=COMMITTED,
                completed_at=int(time.time()),
                recovery_action="recovered after crash: store already carries the target version",
            )
            results.append(
                RecoveryResult(journal_id, store_name, COMMITTED, "marked committed", f"version {current}")
            )
        else:
            detail = (
                f"store version is {current}, target was {target}"
                if current is not None
                else "store is unreadable"
            )
            _update(
                base_dir,
                journal_id,
                state=RECOVERY_REQUIRED,
                error=detail,
                recovery_action=(
                    "Do not replay automatically. The pre-migration snapshot is preserved; "
                    "restore it or run an explicit repair after reviewing the store."
                ),
            )
            results.append(
                RecoveryResult(journal_id, store_name, RECOVERY_REQUIRED, "preserved for review", detail)
            )
    return results


__all__ = [
    "ACTIVE_STATES",
    "APPLYING",
    "BACKUP_CREATED",
    "COMMITTED",
    "FAILED",
    "JOURNAL_RELPATH",
    "MigrationJournalError",
    "PENDING",
    "PREPARING",
    "RECOVERY_REQUIRED",
    "ROLLED_BACK",
    "SNAPSHOT_DIR",
    "VALIDATING",
    "begin",
    "create_snapshot",
    "entries",
    "journal_path",
    "mark_applying",
    "mark_backup_created",
    "mark_committed",
    "mark_failed",
    "mark_validating",
    "pending",
    "reconcile",
]
