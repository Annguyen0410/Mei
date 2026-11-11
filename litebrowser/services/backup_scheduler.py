"""Automatic backup scheduling for a running Mei profile.

This is deliberately an in-process scheduler, not an OS service: Mei cannot
honestly claim a backup will happen while the application is closed.  The
running shell asks :class:`BackupScheduler` whether a daily/weekly backup is due;
the scheduler serializes attempts, refuses to run while a restore or migration
needs review, and records failures without advancing the successful-backup
timestamp.

``due_for_backup`` derives the last successful timestamp from verified archive
metadata, so a failed attempt cannot make the next launch believe it succeeded.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from litebrowser.core import migration_journal, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.storage_utils import write_json
from litebrowser.services import backup_service, restore_service

_log = get_logger("backup_scheduler")

STATE_RELPATH = os.path.join("Recovery", "backup_scheduler_state.json")
_ATTEMPT_LOCK = threading.Lock()


class BackupSchedulerError(OSError):
    """A scheduled backup could not be considered safely."""


@dataclass
class SchedulerResult:
    status: str
    ok: bool = False
    path: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "ok": self.ok,
            "path": self.path,
            "error": self.error,
        }


@dataclass
class SchedulerState:
    last_attempt_at: int = 0
    last_success_at: int = 0
    last_status: str = "never"
    last_error: str = ""
    running: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "running": self.running,
            **self.extra,
        }


def state_path(base_dir: str) -> str:
    return os.path.join(base_dir, STATE_RELPATH)


def _read_state(base_dir: str) -> dict:
    result = storage_health.read_json_checked(state_path(base_dir), dict)
    return dict(result.value) if result.ok else {}


def _write_state(base_dir: str, state: SchedulerState) -> None:
    try:
        write_json(state_path(base_dir), state.as_dict(), allow_replace_corrupt=True)
    except OSError as exc:
        _log.warning("could not persist backup scheduler state: %s", exc)


def _restore_needs_review(base_dir: str) -> bool:
    result = storage_health.read_json_checked(restore_service.journal_path(base_dir), dict)
    if not result.ok:
        return result.status != "missing"
    return str(result.value.get("state") or "") not in (
        "",
        "COMMITTED",
        "ROLLED_BACK",
        "FAILED",
    )


def _migration_needs_review(base_dir: str) -> bool:
    for entry in migration_journal.entries(base_dir):
        if entry.get("state") == migration_journal.RECOVERY_REQUIRED:
            return True
        if entry.get("state") in migration_journal.ACTIVE_STATES:
            return True
    return False


class BackupScheduler:
    """Check-and-run helper; safe to call from a GUI timer or a worker."""

    def __init__(self, base_dir: str, *, clock=time.time):
        self.base_dir = base_dir
        self.clock = clock
        self._thread_lock = threading.Lock()

    def status(self, *, now: int | None = None) -> dict:
        policy = backup_service.load_policy(self.base_dir)
        persisted = _read_state(self.base_dir)
        due = backup_service.due_for_backup(self.base_dir, now=now)
        return {
            "enabled": bool(policy.enabled),
            "frequency": policy.frequency,
            "protection": backup_service.scheduled_protection_status(self.base_dir),
            "due": bool(due),
            "running": bool(self._thread_lock.locked()),
            "restore_requires_review": _restore_needs_review(self.base_dir),
            "migration_requires_review": _migration_needs_review(self.base_dir),
            "last_attempt_at": int(persisted.get("last_attempt_at") or 0),
            "last_success_at": int(persisted.get("last_success_at") or 0),
            "last_status": str(persisted.get("last_status") or "never"),
            "last_error": str(persisted.get("last_error") or ""),
        }

    def run_if_due(self, *, now: int | None = None) -> SchedulerResult:
        """Run one due backup, or explain why no backup was attempted.

        A second concurrent call is refused rather than queued: the first call
        owns the artifact, and queueing would only create duplicate archives.
        """
        moment = int(now if now is not None else self.clock())
        if not _ATTEMPT_LOCK.acquire(blocking=False):
            return SchedulerResult("already_running")
        try:
            if not self._thread_lock.acquire(blocking=False):
                return SchedulerResult("already_running")
            try:
                return self._run_locked(moment)
            finally:
                self._thread_lock.release()
        finally:
            _ATTEMPT_LOCK.release()

    def _run_locked(self, moment: int) -> SchedulerResult:
        if _restore_needs_review(self.base_dir):
            return self._finish(
                moment, SchedulerResult("blocked_restore_review")
            )
        if _migration_needs_review(self.base_dir):
            return self._finish(
                moment, SchedulerResult("blocked_migration_review")
            )
        protection = backup_service.scheduled_protection_status(self.base_dir)
        if not protection.get("ok"):
            return self._finish(
                moment,
                SchedulerResult(
                    "blocked_" + str(protection.get("reason") or "protection"),
                    error=str(protection.get("warning") or ""),
                ),
            )
        if not backup_service.due_for_backup(self.base_dir, now=moment):
            return self._finish(moment, SchedulerResult("not_due"))
        result = backup_service.create_backup(
            self.base_dir, kind="scheduled", now=moment
        )
        if not result.ok:
            _log.warning("scheduled backup failed: %s", result.error)
            return self._finish(
                moment,
                SchedulerResult("failed", error=result.error),
            )
        try:
            backup_service.apply_retention(
                backup_service.load_policy(self.base_dir).destination,
                backup_service.load_policy(self.base_dir),
                now=moment,
            )
        except OSError as exc:
            # The archive is already verified and published.  Retention failure
            # is reported but must not turn a successful backup into a failure.
            _log.warning("scheduled backup retention failed: %s", exc)
        return self._finish(
            moment,
            SchedulerResult("created", ok=True, path=result.path),
        )

    def _finish(self, moment: int, result: SchedulerResult) -> SchedulerResult:
        previous = _read_state(self.base_dir)
        state = SchedulerState(
            last_attempt_at=moment,
            last_success_at=(
                moment
                if result.ok
                else int(previous.get("last_success_at") or 0)
            ),
            last_status=result.status,
            last_error=result.error,
            running=False,
        )
        _write_state(self.base_dir, state)
        return result


__all__ = [
    "BackupScheduler",
    "BackupSchedulerError",
    "SchedulerResult",
    "SchedulerState",
    "STATE_RELPATH",
    "state_path",
]
