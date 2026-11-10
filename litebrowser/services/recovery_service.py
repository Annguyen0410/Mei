"""Startup recovery inspection and safe cleanup.

A profile lock is released by the OS when a process dies, so the presence of a
lock file is not evidence of a crash.  Instead Mei writes a session marker at
startup (``clean_exit: false``) and flips it only on an orderly shutdown.

The marker is a hint, not a transaction.  Recovery decisions come from the
migration journal, the restore journal, atomic-write temp files and backup
artifacts.  Safe facts (a migration whose store already reached its target) are
reconciled automatically; ambiguous states are left for an explicit decision.
"""
from __future__ import annotations

import os
import time
import uuid

from litebrowser.core import migration_journal, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import write_json
from litebrowser.services import backup_service, restore_service

_log = get_logger("recovery_service")

SESSION_RELPATH = os.path.join("Recovery", "session_state.json")
REPORT_RELPATH = os.path.join("Recovery", "last_startup_report.json")
STALE_TEMP_SECONDS = 24 * 60 * 60
TEMP_SUFFIXES = (".tmp", ".part")


def session_path(base_dir: str) -> str:
    return os.path.join(base_dir, SESSION_RELPATH)


def report_path(base_dir: str) -> str:
    return os.path.join(base_dir, REPORT_RELPATH)


def begin_session(base_dir: str, *, pid: int | None = None, now: int | None = None) -> dict:
    """Record an unclean state before any window is shown."""
    state = {
        "kind": "mei.session",
        "version": 1,
        "session_id": uuid.uuid4().hex,
        "pid": int(pid if pid is not None else os.getpid()),
        "started_at": int(now or time.time()),
        "last_update": int(now or time.time()),
        "clean_exit": False,
        "ended_at": 0,
    }
    with profile_locked(base_dir):
        write_json(session_path(base_dir), state)
    return state


def touch_session(base_dir: str, *, now: int | None = None) -> None:
    state = _read_session(base_dir)
    if not state:
        return
    state["last_update"] = int(now or time.time())
    with profile_locked(base_dir):
        write_json(session_path(base_dir), state)


def end_session(base_dir: str, *, now: int | None = None) -> dict:
    state = _read_session(base_dir) or begin_session(base_dir)
    state["clean_exit"] = True
    state["ended_at"] = int(now or time.time())
    state["last_update"] = state["ended_at"]
    with profile_locked(base_dir):
        write_json(session_path(base_dir), state)
    return state


def _read_session(base_dir: str) -> dict:
    result = storage_health.read_json_checked(session_path(base_dir), dict)
    return dict(result.value) if result.ok else {}


def _stale_temps(base_dir: str, *, now: int) -> list[dict]:
    cutoff = int(now) - STALE_TEMP_SECONDS
    rows = []
    for current, dirs, files in os.walk(base_dir, followlinks=False):
        dirs[:] = [name for name in dirs if name not in ("BrowserData", "Recovery")]
        for name in files:
            if not name.startswith(".") or not name.endswith(TEMP_SUFFIXES):
                continue
            path = os.path.join(current, name)
            if os.path.islink(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if stat.st_mtime > cutoff:
                continue
            rows.append(
                {
                    "path": os.path.relpath(path, base_dir).replace("\\", "/"),
                    "size": stat.st_size,
                    "modified_at": int(stat.st_mtime),
                }
            )
    return rows


def inspect_startup(base_dir: str, *, now: int | None = None) -> dict:
    """Describe what the previous session left behind, without changing it."""
    now = int(now or time.time())
    marker = _read_session(base_dir)
    pending = migration_journal.entries(base_dir)
    pending = [
        entry
        for entry in pending
        if entry.get("state") in migration_journal.ACTIVE_STATES
        or entry.get("state") == migration_journal.RECOVERY_REQUIRED
    ]
    restore = storage_health.read_json_checked(restore_service.journal_path(base_dir), dict)
    restore_state = str(restore.value.get("state") or "") if restore.ok else ""
    policy = backup_service.load_policy(base_dir)
    incomplete = []
    try:
        names = os.listdir(policy.destination) if os.path.isdir(policy.destination) else []
    except OSError:
        names = []
    for name in names:
        if ".mei-backup.zip." in name and (name.endswith(".part") or name.endswith(".failed")):
            incomplete.append(name)
    return {
        "generated_at": now,
        "profile": os.path.basename(os.path.normpath(base_dir)),
        "session": marker,
        "unclean_previous_session": bool(marker and not marker.get("clean_exit")),
        "pending_migrations": [dict(entry) for entry in pending],
        "restore_state": restore_state,
        "incomplete_backups": incomplete,
        "stale_temp_files": _stale_temps(base_dir, now=now),
        "quarantine_count": len(storage_health.list_quarantine(base_dir)),
    }


def _remove_temp_after_copy(base_dir: str, relative: str, record: dict) -> bool:
    path = os.path.join(base_dir, *relative.split("/"))
    expected = str(record.get("sha256") or "")
    if not expected or storage_health.file_sha256(path) != expected:
        return False
    try:
        os.unlink(path)
        return True
    except OSError as exc:
        _log.warning("could not remove stale temp %s: %s", relative, exc)
        return False


def recover_startup(base_dir: str, *, now: int | None = None) -> dict:
    """Apply only safe recovery actions and write a report.

    * unfinished migrations are reconciled against the store's actual version;
    * stale atomic-write temp files are copied to quarantine, then removed only
      if their checksum still matches the copy;
    * an unfinished restore is never replayed, and an incomplete backup is
      never published.
    """
    now = int(now or time.time())
    before = inspect_startup(base_dir, now=now)
    migrations = migration_journal.reconcile(base_dir)
    quarantined = []
    for row in before["stale_temp_files"]:
        path = os.path.join(base_dir, *str(row["path"]).split("/"))
        try:
            record = storage_health.quarantine_file(
                base_dir,
                path,
                category="stale_temp",
                reason="stale atomic-write temporary file",
                detail=f"older than {STALE_TEMP_SECONDS} seconds",
            )
            removed = _remove_temp_after_copy(base_dir, str(row["path"]), record)
            quarantined.append({"file": row["path"], "removed": removed, "artifact": record["artifact"]})
        except storage_health.StorageHealthError as exc:
            quarantined.append({"file": row["path"], "removed": False, "error": str(exc)})
    report = {
        "kind": "mei.startup_recovery",
        "version": 1,
        "generated_at": now,
        "inspection": before,
        "migration_reconciliation": [row.as_dict() for row in migrations],
        "stale_temp_quarantine": quarantined,
        "restore_requires_review": before["restore_state"] not in ("", "COMMITTED", "FAILED"),
        "backup_requires_review": before["incomplete_backups"],
        "status": "review_required"
        if before["pending_migrations"] or before["restore_state"] not in ("", "COMMITTED", "FAILED")
        else "recovered",
    }
    with profile_locked(base_dir):
        write_json(report_path(base_dir), report)
    if before["unclean_previous_session"]:
        _log.info("previous session did not shut down cleanly; recovery report written")
    return report


__all__ = [
    "REPORT_RELPATH",
    "SESSION_RELPATH",
    "begin_session",
    "end_session",
    "inspect_startup",
    "recover_startup",
    "report_path",
    "session_path",
    "touch_session",
]
