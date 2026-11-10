"""Read-only profile integrity scanning.

A scan never repairs, rewrites or deletes anything.  It reads stores through
:mod:`storage_health`, classifies what it finds, and returns a redacted report:
record identifiers are hashed, note text and secrets never appear.

The first scan is intentionally conservative.  A finding means "a person should
look at this", not "Mei may silently fix it".  Repair is a separate, explicitly
confirmed operation; the safe default is to preserve the bytes and restore from
a verified backup.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field

from litebrowser.core import migration_journal, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.storage_catalog import STORES, StoreDescriptor
from litebrowser.core.storage_utils import damaged_paths

_log = get_logger("integrity_service")

CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
INFORMATIONAL = "INFORMATIONAL"
SEVERITIES = (CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL)

RESTORE_JOURNAL = os.path.join("Recovery", "restore_journal.json")
EXPECTED_VERSIONS = {
    "tab_sets.json": 4,
    "personal_plan.json": 2,
    "flashcards.json": 1,
    "prefs.json": 2,
    "profile_meta.json": 2,
}
TIMESTAMP_KEYS = ("created_at", "updated_at", "due_at", "due", "completed_at", "started_at")


class IntegrityError(OSError):
    """A repair was requested without the required explicit authorization."""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    code: str
    severity: str
    store: str
    message: str
    record: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.finding_id,
            "code": self.code,
            "severity": self.severity,
            "store": self.store,
            "message": self.message,
            "record": self.record,
        }


@dataclass
class ScanReport:
    started_at: int
    finished_at: int = 0
    status: str = "running"
    stores_inspected: int = 0
    records_inspected: int = 0
    findings: list[Finding] = field(default_factory=list)
    notes_inspected: int = 0
    cancelled: bool = False
    read_only: bool = True

    def add(self, code: str, severity: str, store: str, message: str, record: str = "") -> None:
        ref = _ref(record) if record else ""
        digest = hashlib.sha256(f"{code}|{store}|{ref}".encode("utf-8")).hexdigest()[:16]
        self.findings.append(Finding(digest, code, severity, store, message, ref))

    def summary(self) -> dict:
        counts = {severity: 0 for severity in SEVERITIES}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        if counts[CRITICAL]:
            status = "critical"
        elif counts[HIGH]:
            status = "attention"
        elif counts[MEDIUM] or counts[LOW]:
            status = "warnings"
        else:
            status = "healthy"
        return {
            "status": status,
            "findings": len(self.findings),
            "by_severity": counts,
        }

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "read_only": True,
            "stores_inspected": self.stores_inspected,
            "records_inspected": self.records_inspected,
            "notes_inspected": self.notes_inspected,
            "cancelled": self.cancelled,
            "summary": self.summary(),
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _ref(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()[:8]


def _cancelled(cancel) -> bool:
    try:
        return bool(cancel and cancel())
    except Exception:
        return False


def _rows(descriptor: StoreDescriptor, payload):
    if descriptor.root == "list":
        return payload if isinstance(payload, list) else None
    if not isinstance(payload, dict):
        return None
    if not descriptor.collection:
        return None
    value = payload.get(descriptor.collection)
    return value if isinstance(value, list) else None


def _valid_timestamp(value) -> bool:
    if value in (None, "", 0):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value >= 0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        try:
            float(text)
            return True
        except (TypeError, ValueError, OverflowError):
            pass
        try:
            from datetime import datetime

            datetime.fromisoformat(text.replace("Z", "+00:00"))
            return True
        except (ValueError, OSError, OverflowError):
            return False
    return False


def _check_rows(report: ScanReport, descriptor: StoreDescriptor, payload) -> list[dict]:
    rows = _rows(descriptor, payload)
    if rows is None:
        if descriptor.collection and isinstance(payload, dict):
            report.add(
                "collection_missing",
                HIGH,
                descriptor.name,
                f"expected a list at '{descriptor.collection}'",
            )
        return []
    report.records_inspected += len(rows)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            report.add("row_not_object", MEDIUM, descriptor.name, "a collection row is not an object")
            continue
        raw_id = row.get(descriptor.id_key)
        if raw_id in (None, ""):
            report.add("row_without_id", LOW, descriptor.name, "a record has no stable identifier", f"#{index}")
        else:
            identifier = str(raw_id)[:512]
            if identifier in seen:
                report.add(
                    "duplicate_id",
                    MEDIUM,
                    descriptor.name,
                    "more than one record uses the same identifier",
                    identifier,
                )
            seen.add(identifier)
        for key in TIMESTAMP_KEYS:
            if key in row and not _valid_timestamp(row.get(key)):
                report.add(
                    "invalid_timestamp",
                    LOW,
                    descriptor.name,
                    f"record has an invalid '{key}' value",
                    str(raw_id or f"#{index}"),
                )
                break
    return rows


def _check_plan(report: ScanReport, base_dir: str, payload) -> None:
    if not isinstance(payload, dict):
        return
    courses = {
        str(row.get("id"))
        for row in payload.get("courses", [])
        if isinstance(row, dict) and row.get("id")
    }
    for row in payload.get("items", []):
        if isinstance(row, dict) and row.get("course_id") and str(row["course_id"]) not in courses:
            report.add(
                "orphan_course_reference",
                LOW,
                "personal_plan.json",
                "planner item references a course that is not present",
                str(row.get("id") or ""),
            )
    for row in payload.get("time_blocks", []):
        if isinstance(row, dict) and row.get("course_id") and str(row["course_id"]) not in courses:
            report.add(
                "orphan_course_reference",
                LOW,
                "personal_plan.json",
                "planner time block references a course that is not present",
                str(row.get("id") or ""),
            )


def _note_ids(base_dir: str) -> set[str]:
    root = os.path.join(base_dir, "SafeVault", "notes")
    if not os.path.isdir(root):
        return set()
    found = set()
    for current, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            if not name.lower().endswith((".md", ".txt")):
                continue
            path = os.path.join(current, name)
            if os.path.islink(path):
                continue
            found.add(os.path.relpath(path, root).replace("/", os.sep))
    return found


def _check_research(report: ScanReport, base_dir: str, payload) -> None:
    if not isinstance(payload, dict):
        return
    notes = _note_ids(base_dir)
    task_ids = _ids(base_dir, "tasks.json")
    page_ids = _ids(base_dir, "saved_pages.json")
    card_ids = _ids(base_dir, "flashcards.json", collection="cards")
    for workspace in payload.get("sets", []):
        if not isinstance(workspace, dict) or workspace.get("kind") != "workspace":
            continue
        checks = (
            ("notes", notes, "note"),
            ("tasks", task_ids, "task"),
            ("saved_pages", page_ids, "saved page"),
            ("flashcards", card_ids, "flashcard"),
        )
        for field_name, known, label in checks:
            for reference in workspace.get(field_name, []) if isinstance(workspace.get(field_name), list) else []:
                if str(reference) not in known:
                    report.add(
                        "orphan_research_reference",
                        LOW,
                        "tab_sets.json",
                        f"research workspace references a missing {label}",
                        str(workspace.get("id") or ""),
                    )


def _ids(base_dir: str, name: str, collection: str = "") -> set[str]:
    result = storage_health.read_json_checked(os.path.join(base_dir, name), (list, dict))
    if not result.ok:
        return set()
    rows = result.value if isinstance(result.value, list) else result.value.get(collection, [])
    return {
        str(row.get("id"))
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("id")
    }


def _scan_notes(report: ScanReport, base_dir: str, cancel) -> None:
    root = os.path.join(base_dir, "SafeVault", "notes")
    if not os.path.isdir(root):
        return
    for current, dirs, files in os.walk(root, followlinks=False):
        if _cancelled(cancel):
            report.cancelled = True
            return
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            path = os.path.join(current, name)
            if os.path.islink(path):
                report.add("note_symlink", LOW, "notes", "a note is a symlink and was not followed", name)
                continue
            if not name.lower().endswith((".md", ".txt")):
                continue
            report.notes_inspected += 1
            try:
                if os.path.getsize(path) == 0:
                    report.add("empty_note", LOW, "notes", "a note file is empty", name)
                    continue
                with open(path, "rb") as handle:
                    raw = handle.read(MAX_NOTE_SCAN_BYTES)
                raw.decode("utf-8")
            except UnicodeDecodeError:
                report.add("note_invalid_utf8", MEDIUM, "notes", "a note is not valid UTF-8", name)
            except OSError:
                report.add("note_unreadable", MEDIUM, "notes", "a note could not be read", name)


MAX_NOTE_SCAN_BYTES = 16 * 1024 * 1024


def scan(base_dir: str, *, cancel=None, now: int | None = None) -> dict:
    """Inspect the profile without writing a single byte."""
    started = int(time.time())
    report = ScanReport(started_at=started)
    current_year = time.gmtime(now or time.time()).tm_year
    for descriptor in STORES:
        if _cancelled(cancel):
            report.cancelled = True
            break
        path = os.path.join(base_dir, descriptor.name)
        result = storage_health.read_json_checked(
            path, dict if descriptor.root == "dict" else list
        )
        if result.status == "missing":
            continue
        report.stores_inspected += 1
        if not result.ok:
            severity = CRITICAL if result.status in ("malformed_json", "invalid_encoding") else HIGH
            report.add(
                f"store_{result.status}",
                severity,
                descriptor.name,
                f"store cannot be interpreted: {result.status} ({result.detail})",
            )
            continue
        payload = result.value
        expected = EXPECTED_VERSIONS.get(descriptor.name)
        if expected is not None and isinstance(payload, dict):
            try:
                version = int(payload.get(descriptor.version_key, 1) or 1)
            except (TypeError, ValueError, OverflowError):
                version = 0
            if version > expected:
                report.add(
                    "future_schema",
                    HIGH,
                    descriptor.name,
                    f"store schema is {version}, this build understands {expected}",
                )
        rows = _check_rows(report, descriptor, payload)
        for row in rows:
            for key in ("created_at", "updated_at"):
                value = row.get(key) if isinstance(row, dict) else None
                if isinstance(value, (int, float)) and value > 0:
                    stamp_year = time.gmtime(value).tm_year
                    if stamp_year > current_year + 10:
                        report.add(
                            "implausible_future_timestamp",
                            LOW,
                            descriptor.name,
                            f"record timestamp is far in the future ({stamp_year})",
                            str(row.get("id") or ""),
                        )
                        break
        if descriptor.name == "personal_plan.json":
            _check_plan(report, base_dir, payload)
        if descriptor.name == "tab_sets.json":
            _check_research(report, base_dir, payload)
    if not report.cancelled:
        _scan_notes(report, base_dir, cancel)
    if not report.cancelled:
        try:
            journal = migration_journal.entries(base_dir)
        except Exception:
            journal = []
        for entry in journal:
            if entry.get("state") in migration_journal.ACTIVE_STATES:
                report.add(
                    "migration_incomplete",
                    HIGH,
                    "migration_journal.json",
                    "a store migration did not reach a terminal state",
                    str(entry.get("id") or ""),
                )
            elif entry.get("state") == migration_journal.RECOVERY_REQUIRED:
                report.add(
                    "migration_recovery_required",
                    HIGH,
                    "migration_journal.json",
                    "a store migration needs an explicit recovery decision",
                    str(entry.get("id") or ""),
                )
        restore = storage_health.read_json_checked(os.path.join(base_dir, RESTORE_JOURNAL), dict)
        if restore.ok and restore.value.get("state") not in (None, "COMMITTED", "FAILED"):
            report.add(
                "restore_incomplete",
                HIGH,
                "restore_journal.json",
                "a restore did not reach a terminal state",
            )
        for path, artifact in damaged_paths().items():
            relative = os.path.relpath(path, base_dir)
            if relative.startswith(".."):
                continue
            report.add(
                "legacy_store_write_blocked",
                HIGH,
                relative.replace("\\", "/"),
                "a malformed legacy store is preserved and write-protected"
                + (f"; copy: {os.path.basename(artifact)}" if artifact else ""),
            )
        quarantined = storage_health.list_quarantine(base_dir)
        if quarantined:
            report.add(
                "quarantine_artifacts",
                INFORMATIONAL,
                "Recovery/quarantine",
                f"{len(quarantined)} quarantined artifact(s) are available for inspection",
            )
    report.finished_at = int(time.time())
    report.status = "cancelled" if report.cancelled else "complete"
    return report.as_dict()


def repair_plan(report: dict) -> list[dict]:
    """Turn findings into explicit, non-destructive suggestions."""
    plan = []
    for finding in report.get("findings", []):
        if not isinstance(finding, dict):
            continue
        code = str(finding.get("code") or "")
        if code.startswith("store_") or code in ("collection_missing",):
            action = "Restore this store from a verified backup, or quarantine it and inspect the copy."
        elif code == "future_schema":
            action = "Do not edit this store with this build. Update Mei or restore a compatible backup."
        elif code == "migration_recovery_required":
            action = "Review the migration snapshot; do not replay the migration automatically."
        elif code in ("duplicate_id", "orphan_course_reference", "orphan_research_reference"):
            action = "Review the referenced records and merge or relink them explicitly."
        else:
            action = "Review the record; no automatic change is recommended."
        plan.append({"finding_id": finding.get("id"), "action": action})
    return plan


def quarantine_store(base_dir: str, store_name: str, *, confirm: bool = False) -> dict:
    """Copy a damaged store into quarantine after explicit confirmation.

    The live store is left in place.  A pre-repair backup is attempted first so
    the user has an independent copy; failure to create it aborts the repair.
    """
    if not confirm:
        raise IntegrityError("Quarantining a store requires explicit confirmation.")
    from litebrowser.services import backup_service

    descriptor = next((item for item in STORES if item.name == store_name), None)
    if descriptor is None:
        raise IntegrityError("Unknown store.")
    path = os.path.join(base_dir, descriptor.name)
    checked = storage_health.read_json_checked(
        path, dict if descriptor.root == "dict" else list
    )
    if checked.ok:
        raise IntegrityError("That store is readable; there is nothing to quarantine.")
    backup = backup_service.create_backup(base_dir, kind="pre-repair")
    if not backup.ok:
        raise IntegrityError(f"Refusing to repair without a verified backup: {backup.error}")
    record = storage_health.quarantine_file(
        base_dir,
        path,
        category=store_name,
        reason=checked.status,
        detail=checked.detail,
    )
    record["pre_repair_backup"] = backup.path
    return record


__all__ = [
    "CRITICAL",
    "HIGH",
    "INFORMATIONAL",
    "IntegrityError",
    "LOW",
    "MEDIUM",
    "SEVERITIES",
    "quarantine_store",
    "repair_plan",
    "scan",
]
