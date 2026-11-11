"""Staged profile restore with a durable, crash-recoverable transaction.

Restore is a filesystem operation across several stores, so it is not one atomic
transaction.  The journal records every target, its original hash, the staged
hash and a verified rollback copy *before* anything is replaced.  Recovery on
the next startup compares the live bytes with those hashes: an unambiguously
complete transaction is committed, an unambiguously untouched or partially
applied transaction is rolled back from verified originals, and anything else
is left in ``RECOVERY_REQUIRED`` without deleting evidence.

Credentials are never in a backup (``backup_service`` excludes them), so a
restore cannot roll back a newly signed-in secret to an older value.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field

from litebrowser.core import app_paths, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_catalog import RESTORE_GROUPS, STORES_BY_NAME
from litebrowser.core.storage_utils import safe_child_path, tempfile_mkstemp_same_dir, write_json
from litebrowser.services import backup_service, conflict_service

_log = get_logger("restore_service")

JOURNAL_RELPATH = os.path.join("Recovery", "restore_journal.json")
STAGING_RELPATH = os.path.join("Recovery", "restore_staging")
JOURNAL_VERSION = 2
MAX_MEMBER_BYTES = backup_service.MAX_FILE_BYTES
MAX_TOTAL_BYTES = backup_service.MAX_TOTAL_BYTES
NOTES_PREFIX = "SafeVault/notes/"
ALL_GROUPS = tuple(sorted(set(RESTORE_GROUPS) | {"notes"}))
RESOLVED_STATES = frozenset({"COMMITTED", "ROLLED_BACK", "FAILED"})


class RestoreError(OSError):
    """A restore was refused or could not complete safely."""


@dataclass
class RestoreResult:
    ok: bool
    status: str
    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error: str = ""
    pre_restore_backup: str = ""
    journal_path: str = ""
    rollback: str = ""
    pre_restore_protection: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "restored": self.restored,
            "skipped": self.skipped,
            "error": self.error,
            "pre_restore_backup": self.pre_restore_backup,
            "journal_path": self.journal_path,
            "rollback": self.rollback,
            "pre_restore_protection": self.pre_restore_protection,
        }


def journal_path(base_dir: str) -> str:
    return os.path.join(base_dir, JOURNAL_RELPATH)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    """Stream a file hash; missing and unreadable files have no hash."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return ""


TARGET_ORIGINAL = "ORIGINAL"
TARGET_STAGED = "STAGED"
TARGET_MISSING = "MISSING"
TARGET_UNKNOWN = "UNKNOWN"
TARGET_UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class TargetProbe:
    """What one restore target actually is right now.

    ``_sha256_file`` returns an empty string for both a missing file and an I/O
    failure.  Rollback must never treat those as the same thing: restoring over
    a target that exists but could not be read would destroy whatever it holds.
    """

    path: str
    exists: bool
    readable: bool
    sha256: str = ""
    detail: str = ""


def _probe_file(path: str) -> TargetProbe:
    """Inspect one target without collapsing missing into unreadable."""
    import stat as stat_module

    try:
        info = os.stat(path)
    except FileNotFoundError:
        return TargetProbe(path=path, exists=False, readable=False)
    except NotADirectoryError:
        return TargetProbe(path=path, exists=False, readable=False)
    except PermissionError as exc:
        return TargetProbe(path=path, exists=True, readable=False, detail=str(exc))
    except OSError as exc:
        return TargetProbe(path=path, exists=True, readable=False, detail=str(exc))
    if stat_module.S_ISDIR(info.st_mode):
        return TargetProbe(
            path=path, exists=True, readable=False, detail="target is a directory"
        )
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except FileNotFoundError:
        return TargetProbe(path=path, exists=False, readable=False)
    except (PermissionError, OSError) as exc:
        return TargetProbe(path=path, exists=True, readable=False, detail=str(exc))
    return TargetProbe(path=path, exists=True, readable=True, sha256=digest.hexdigest())


def _classify_target(path: str, entry: dict) -> tuple[str, TargetProbe]:
    """Classify a journal target as ORIGINAL, STAGED, MISSING, UNKNOWN or UNREADABLE."""
    probe = _probe_file(path)
    if not probe.exists:
        return TARGET_MISSING, probe
    if not probe.readable:
        return TARGET_UNREADABLE, probe
    original_exists = bool(entry.get("original_exists"))
    original_sha = str(entry.get("original_sha") or "")
    staged_sha = str(entry.get("staged_sha") or "")
    if original_exists and original_sha and probe.sha256 == original_sha:
        return TARGET_ORIGINAL, probe
    if staged_sha and probe.sha256 == staged_sha:
        return TARGET_STAGED, probe
    return TARGET_UNKNOWN, probe


def _write_bytes_atomic(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile_mkstemp_same_dir(parent, os.path.basename(path))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _row_group(path: str, category: str) -> str:
    if path.startswith(NOTES_PREFIX) or category == "notes":
        return "notes"
    descriptor = STORES_BY_NAME.get(path)
    return descriptor.restore_group if descriptor else ""


def _selected(categories) -> set[str] | None:
    """Resolve restore categories without collapsing empty into "all".

    ``None`` is the one explicit all-categories value.  An empty list/tuple/set
    is an invalid selection and is rejected by the service, independently of
    the UI.  Duplicate categories are normalised, unknown categories fail.
    """
    if categories is None:
        return None
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, (list, tuple, set, frozenset)):
        raise RestoreError("Restore categories must be a list, tuple, set or None.")
    result = {
        str(item).strip()
        for item in categories
        if isinstance(item, str) and str(item).strip()
    }
    if not result:
        raise RestoreError("No restore categories were selected; nothing was restored.")
    unknown = result - set(ALL_GROUPS)
    if unknown:
        raise RestoreError("Unknown restore category: " + ", ".join(sorted(unknown)))
    return result


def _record_count(path: str, payload) -> int | None:
    descriptor = STORES_BY_NAME.get(path)
    if descriptor is None:
        return None
    if descriptor.root == "list":
        return len(payload) if isinstance(payload, list) else None
    if descriptor.collection and isinstance(payload, dict):
        rows = payload.get(descriptor.collection)
        return len(rows) if isinstance(rows, list) else None
    return None


def _preview_plain(base_dir: str, backup_path: str, *, categories=None) -> dict:
    """Describe exactly which files would change and how many records differ."""
    selected = _selected(categories)
    checked = backup_service.verify_backup(backup_path)
    if not checked["ok"]:
        return {
            "ok": False,
            "status": checked["status"],
            "error": "; ".join(checked["errors"]) or "Backup is not valid.",
            "files": [],
        }
    manifest = checked["manifest"]
    files = []
    warnings = []
    totals = {"added": 0, "replaced": 0, "unchanged": 0, "removed": 0}
    for row in manifest.get("files", []):
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        category = str(row.get("category") or "")
        group = _row_group(path, category)
        if selected is not None and group not in selected and category not in selected:
            continue
        if not group and not path.startswith(NOTES_PREFIX):
            warnings.append(f"unknown file in backup was ignored: {path}")
            continue
        current_path = safe_child_path(base_dir, path)
        if not current_path:
            warnings.append(f"unsafe path in backup was ignored: {path}")
            continue
        exists = os.path.isfile(current_path)
        current_sha = storage_health.file_sha256(current_path) if exists else ""
        changed = current_sha != str(row.get("sha256") or "")
        if (
            exists
            and path.replace("\\", "/")
            == conflict_service.STORE_RELPATH.replace("\\", "/")
        ):
            try:
                current_conflicts = storage_health.read_json_checked(current_path, dict)
                with zipfile.ZipFile(backup_path, "r") as archive:
                    incoming_conflicts = json.loads(archive.read(path).decode("utf-8"))
                if current_conflicts.ok:
                    _merged, added = conflict_service.merge_payload(
                        current_conflicts.value, incoming_conflicts
                    )
                    # An old archive that adds no new conflict is a no-op, not
                    # a replacement of the newer live archive.
                    changed = bool(added)
            except (OSError, ValueError, UnicodeError, KeyError, zipfile.BadZipFile):
                changed = True
        entry = {
            "path": path,
            "category": category,
            "group": group,
            "size": int(row.get("size") or 0),
            "exists": exists,
            "changed": changed,
            "action": ("replaced" if exists else "added") if changed else "unchanged",
            "current_records": None,
            "backup_records": None,
        }
        if path.endswith(".json") and not path.startswith(NOTES_PREFIX):
            try:
                with zipfile.ZipFile(backup_path, "r") as archive:
                    payload = json.loads(archive.read(path).decode("utf-8"))
                entry["backup_records"] = _record_count(path, payload)
            except (OSError, ValueError, UnicodeError, KeyError, zipfile.BadZipFile):
                warnings.append(f"could not count records in {path}")
            if exists:
                current = storage_health.read_json_checked(current_path, (list, dict))
                if current.ok:
                    entry["current_records"] = _record_count(path, current.value)
            expected = {
                "prefs.json": app_paths.APP_SCHEMA_VERSION,
                "profile_meta.json": app_paths.APP_SCHEMA_VERSION,
            }.get(path)
            if expected is None:
                from litebrowser.services import integrity_service

                expected = integrity_service.EXPECTED_VERSIONS.get(path)
            if expected and isinstance(payload, dict):
                try:
                    version = int(
                        payload.get(
                            "schema_version" if path == "prefs.json" else "version", 1
                        )
                        or 1
                    )
                    if version > expected:
                        warnings.append(
                            f"{path} uses schema {version}; this build supports {expected}"
                        )
                except (TypeError, ValueError, OverflowError):
                    pass
        totals[entry["action"]] += 1
        files.append(entry)
    return {
        "ok": True,
        "status": "ready",
        "backup": backup_path,
        "manifest": manifest,
        "files": files,
        "warnings": warnings,
        "totals": totals,
        "categories": sorted(selected) if selected is not None else list(ALL_GROUPS),
    }


def preview(base_dir: str, backup_path: str, *, categories=None, password: str | None = None) -> dict:
    """Preview a plain or encrypted backup without modifying the profile."""
    from litebrowser.services import encrypted_backup_service

    try:
        if not encrypted_backup_service.is_encrypted(backup_path):
            return _preview_plain(base_dir, backup_path, categories=categories)
    except RestoreError as exc:
        return {"ok": False, "status": "invalid_selection", "error": str(exc), "files": []}
    if not password:
        return {
            "ok": False,
            "status": "password_required",
            "error": "This backup is encrypted; enter its password.",
            "files": [],
        }
    try:
        with encrypted_backup_service.materialized(backup_path, password) as plain:
            plan = _preview_plain(base_dir, plain, categories=categories)
        plan["backup"] = backup_path
        plan["encrypted"] = True
        return plan
    except RestoreError as exc:
        return {"ok": False, "status": "invalid_selection", "error": str(exc), "files": []}
    except encrypted_backup_service.EncryptedBackupError as exc:
        return {
            "ok": False,
            "status": exc.status,
            "error": str(exc),
            "files": [],
        }


def _extract_selected(backup_path: str, staging: str, files: list[dict]) -> dict[str, str]:
    extracted: dict[str, str] = {}
    total = 0
    with zipfile.ZipFile(backup_path, "r") as archive:
        total_written = 0
        for row in files:
            arcname = str(row["path"])
            try:
                member = archive.getinfo(arcname)
            except KeyError as exc:
                raise RestoreError(f"Backup does not contain {arcname}.") from exc
            if member.file_size > MAX_MEMBER_BYTES:
                raise RestoreError(f"Backup member is too large: {arcname}")
            total += member.file_size
            if total > MAX_TOTAL_BYTES:
                raise RestoreError("Backup expands beyond the restore limit.")
            target = safe_child_path(staging, arcname)
            if not target:
                raise RestoreError(f"Unsafe restore path: {arcname}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as handle:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    total_written += len(block)
                    if total_written > MAX_MEMBER_BYTES or total_written > MAX_TOTAL_BYTES:
                        raise RestoreError(f"Backup member expands beyond the limit: {arcname}")
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            expected = str(row.get("sha256") or "")
            if expected and _sha256_file(target) != expected:
                raise RestoreError(f"Backup content changed or is corrupt: {arcname}")
            extracted[arcname] = target
    return extracted


def _validate_payload(path: str, data: bytes) -> None:
    descriptor = STORES_BY_NAME.get(path)
    if descriptor is None:
        if path.startswith(NOTES_PREFIX):
            data.decode("utf-8")
        return
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RestoreError(f"{path} is not valid JSON: {exc}") from exc
    if descriptor.root == "dict" and not isinstance(payload, dict):
        raise RestoreError(f"{path} must contain an object.")
    if descriptor.root == "list" and not isinstance(payload, list):
        raise RestoreError(f"{path} must contain a list.")
    expected = None
    if path == "prefs.json":
        expected = app_paths.APP_SCHEMA_VERSION
        version = (
            int(payload.get("schema_version", app_paths.APP_SCHEMA_VERSION) or 0)
            if isinstance(payload, dict)
            else 0
        )
    elif path == "profile_meta.json":
        expected = app_paths.APP_SCHEMA_VERSION
        version = (
            int(payload.get("schema_version", app_paths.APP_SCHEMA_VERSION) or 0)
            if isinstance(payload, dict)
            else 0
        )
    else:
        from litebrowser.services import integrity_service

        expected = integrity_service.EXPECTED_VERSIONS.get(path)
        version = int(payload.get("version", 1) or 1) if isinstance(payload, dict) else 1
    if expected is not None and version > expected:
        raise RestoreError(
            f"{path} was written by a newer schema ({version}); this build supports {expected}."
        )


def _prepare_restore_data(base_dir: str, path: str, data: bytes) -> bytes:
    """Merge special stores instead of replacing their live history.

    Conflict archives are not a normal category: restoring an old backup must
    not erase conflicts created after that backup, and it must not activate a
    remote or local version.  The merge preserves status/resolution and is
    idempotent by the conflict signature.
    """
    if path.replace("\\", "/") != conflict_service.STORE_RELPATH.replace("\\", "/"):
        return data
    try:
        incoming = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise RestoreError(f"{path} is not valid JSON: {exc}") from exc
    current_path = safe_child_path(base_dir, path)
    current = {}
    if current_path and os.path.isfile(current_path):
        checked = storage_health.read_json_checked(current_path, dict)
        if checked.ok:
            current = checked.value
        elif checked.status != "missing":
            raise RestoreError(
                "The live conflict archive is unreadable; restore it explicitly before importing another archive."
            )
    merged, _added = conflict_service.merge_payload(current, incoming)
    return json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _journal(base_dir: str, data: dict) -> str:
    path = journal_path(base_dir)
    data["updated_at"] = int(time.time())
    write_json(path, data)
    return path


def _create_pre_restore(
    base_dir: str,
    *,
    now: int | None,
    encrypted: bool,
    password: str | None,
    allow_plaintext: bool,
) -> tuple[backup_service.BackupResult, str]:
    """Create the pre-restore protection without silently downgrading it."""
    from litebrowser.services import encrypted_backup_service

    if encrypted:
        if not password:
            return (
                backup_service.BackupResult(
                    ok=False,
                    error="An encrypted pre-restore backup needs the backup password; restore was blocked.",
                ),
                "encrypted",
            )
        result = encrypted_backup_service.create_encrypted_backup(
            base_dir, password, kind="pre-restore", now=now
        )
        return result, "encrypted"
    if not allow_plaintext:
        return (
            backup_service.BackupResult(
                ok=False,
                error="An encrypted source cannot create a plaintext pre-restore snapshot. "
                "Use the encrypted pre-restore option or explicitly allow the downgrade.",
            ),
            "plaintext",
        )
    return backup_service.create_backup(base_dir, kind="pre-restore", now=now), "plaintext"


def _entries_from_journal(journal: dict) -> list[dict]:
    values = journal.get("files")
    return [dict(row) for row in values] if isinstance(values, list) else []


def _safe_target(base_dir: str, entry: dict) -> str:
    path = entry.get("path")
    target = safe_child_path(base_dir, str(path or ""))
    if not target:
        raise RestoreError(f"Unsafe restore target in journal: {path!r}")
    return target


def _safe_staged(staging: str, entry: dict) -> str:
    path = entry.get("staged")
    target = safe_child_path(staging, str(path or ""))
    if not target:
        raise RestoreError(f"Unsafe staged path in journal: {path!r}")
    return target


def _safe_rollback(staging: str, entry: dict) -> str:
    path = entry.get("rollback")
    target = safe_child_path(staging, str(path or ""))
    if not target:
        raise RestoreError(f"Unsafe rollback path in journal: {path!r}")
    return target


def _persist_rollback_state(base_dir: str, journal: dict, journal_file: str) -> None:
    """Make each rollback step durable before and after touching a target."""
    if not journal_file:
        return
    journal["updated_at"] = int(time.time())
    write_json(journal_file, journal)


def _rollback_entries(
    base_dir: str,
    journal: dict,
    *,
    journal_file: str = "",
    restore_missing: bool = True,
) -> list[str]:
    """Restore each target from its verified rollback copy.

    Every target is classified first.  A target that is readable but matches
    neither the recorded original nor the recorded staged bytes is left
    untouched: another writer may have produced it, and guessing would destroy
    data.  An unreadable target is never treated as missing.  Both cases are
    reported so the caller records ``RECOVERY_REQUIRED`` and keeps every
    artifact.

    A missing target whose journal proves the original existed may be restored
    from the verified rollback copy when ``restore_missing`` is explicitly set;
    no current bytes exist to overwrite, so this only recovers the last known
    version.
    """
    operation_id = str(journal.get("operation_id") or "")
    if not operation_id:
        return ["journal has no operation id"]
    staging = os.path.join(base_dir, STAGING_RELPATH, operation_id)
    errors: list[str] = []
    with profile_locked(base_dir):
        for entry in reversed(_entries_from_journal(journal)):
            name = entry.get("path")
            try:
                target = _safe_target(base_dir, entry)
                original_exists = bool(entry.get("original_exists"))
                original_sha = str(entry.get("original_sha") or "")
                state, probe = _classify_target(target, entry)
                if original_exists:
                    if state == TARGET_ORIGINAL:
                        entry["status"] = "ORIGINAL"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        continue
                    if state == TARGET_UNKNOWN:
                        errors.append(
                            f"refusing to overwrite changed target {name} during rollback"
                        )
                        entry["status"] = "RECOVERY_REQUIRED"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        continue
                    if state == TARGET_UNREADABLE:
                        errors.append(
                            f"refusing to overwrite unreadable target {name} during rollback"
                        )
                        entry["status"] = "RECOVERY_REQUIRED"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        continue
                    if state == TARGET_MISSING and not restore_missing:
                        errors.append(
                            f"target {name} is missing and the recovery policy does not restore missing targets"
                        )
                        entry["status"] = "RECOVERY_REQUIRED"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        continue
                    if state == TARGET_STAGED or state == TARGET_MISSING:
                        if not original_sha:
                            raise RestoreError(
                                f"journal has no original hash for {name}; refusing an approximate rollback"
                            )
                        rollback = _safe_rollback(staging, entry)
                        rollback_probe = _probe_file(rollback)
                        if not rollback_probe.exists:
                            errors.append(f"rollback copy is missing for {name}")
                            entry["status"] = "RECOVERY_REQUIRED"
                            _persist_rollback_state(base_dir, journal, journal_file)
                            continue
                        if not rollback_probe.readable:
                            errors.append(
                                f"rollback copy is unreadable for {name}: {rollback_probe.detail}"
                            )
                            entry["status"] = "RECOVERY_REQUIRED"
                            _persist_rollback_state(base_dir, journal, journal_file)
                            continue
                        if rollback_probe.sha256 != original_sha:
                            errors.append(f"rollback copy is corrupt for {name}")
                            entry["status"] = "RECOVERY_REQUIRED"
                            _persist_rollback_state(base_dir, journal, journal_file)
                            continue
                        entry["status"] = "ROLLING_BACK"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        with open(rollback, "rb") as handle:
                            data = handle.read()
                        _write_bytes_atomic(target, data)
                        check = _probe_file(target)
                        if not check.readable or check.sha256 != original_sha:
                            errors.append(f"rollback verification failed for {name}")
                            entry["status"] = "RECOVERY_REQUIRED"
                            _persist_rollback_state(base_dir, journal, journal_file)
                            continue
                        entry["status"] = "ROLLED_BACK"
                        _persist_rollback_state(base_dir, journal, journal_file)
                        continue
                    errors.append(
                        f"unexpected rollback state {state} for {name}; target left untouched"
                    )
                    entry["status"] = "RECOVERY_REQUIRED"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    continue
                # The restore created this target; only delete bytes this
                # operation provably wrote.
                if state == TARGET_MISSING:
                    entry["status"] = "ORIGINAL"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    continue
                if state == TARGET_UNKNOWN:
                    errors.append(
                        f"refusing to delete changed target {name} during rollback"
                    )
                    entry["status"] = "RECOVERY_REQUIRED"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    continue
                if state == TARGET_UNREADABLE:
                    errors.append(
                        f"refusing to delete unreadable target {name} during rollback"
                    )
                    entry["status"] = "RECOVERY_REQUIRED"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    continue
                if state == TARGET_STAGED:
                    entry["status"] = "ROLLING_BACK"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    os.remove(target)
                    if os.path.exists(target):
                        errors.append(f"could not remove restored file {name}")
                        entry["status"] = "RECOVERY_REQUIRED"
                    else:
                        entry["status"] = "ROLLED_BACK"
                    _persist_rollback_state(base_dir, journal, journal_file)
                    continue
                errors.append(f"unexpected rollback state {state} for {name}")
                entry["status"] = "RECOVERY_REQUIRED"
                _persist_rollback_state(base_dir, journal, journal_file)
            except Exception as exc:  # each file is independent; report, never guess
                errors.append(f"{name}: {exc}")
                entry["status"] = "RECOVERY_REQUIRED"
                try:
                    _persist_rollback_state(base_dir, journal, journal_file)
                except Exception:
                    pass
    return errors


def recover_interrupted(base_dir: str, *, now: int | None = None) -> dict:
    """Deterministically finish or roll back an interrupted restore.

    Only an unambiguously complete transaction is committed.  If every target
    already equals its staged hash and the pre-restore snapshot exists, the
    commit is safe.  If every target is untouched, the journal is closed without
    touching data.  A partial transaction is rolled back from verified copies;
    anything else is preserved as RECOVERY_REQUIRED.
    """
    _ = now
    journal_file = journal_path(base_dir)
    checked = storage_health.read_json_checked(journal_file, dict)
    if not checked.ok:
        return {
            "status": "none" if checked.status == "missing" else "unreadable",
            "journal_path": journal_file,
            "detail": getattr(checked, "detail", "") or "journal is not readable",
        }
    journal = dict(checked.value)
    if journal.get("version") != JOURNAL_VERSION:
        return {
            "status": "recovery_required",
            "journal_path": journal_file,
            "detail": "legacy restore journal cannot be replayed safely",
        }
    state = str(journal.get("state") or "")
    if state in RESOLVED_STATES:
        return {"status": state.lower(), "journal_path": journal_file, "detail": ""}
    entries = _entries_from_journal(journal)
    try:
        with profile_locked(base_dir):
            if not entries:
                journal["state"] = "FAILED"
                journal["finished_at"] = int(time.time())
                journal["rollback"] = "not_started"
                _journal(base_dir, journal)
                return {"status": "failed", "journal_path": journal_file, "detail": "no files"}
            statuses = []
            for entry in entries:
                target = _safe_target(base_dir, entry)
                state, _probe = _classify_target(target, entry)
                if state == TARGET_ORIGINAL:
                    statuses.append("original")
                elif state == TARGET_STAGED:
                    statuses.append("staged")
                elif state == TARGET_MISSING:
                    # A created target that is still missing is untouched; an
                    # original target that is missing has lost its live bytes.
                    statuses.append(
                        "original" if not bool(entry.get("original_exists")) else "missing"
                    )
                elif state == TARGET_UNREADABLE:
                    statuses.append("unreadable")
                else:
                    statuses.append("unknown")
            pre = str(journal.get("pre_restore_backup") or "")
            all_staged = all(value == "staged" for value in statuses)
            all_original = all(value == "original" for value in statuses)
            if state in ("APPLYING", "PARTIALLY_APPLIED", "VERIFYING") and all_staged:
                if not pre or not os.path.isfile(pre):
                    raise RestoreError("pre-restore snapshot is missing; refusing to commit")
                journal["state"] = "COMMITTED"
                journal["finished_at"] = int(time.time())
                journal["commit_recovered"] = True
                _journal(base_dir, journal)
                return {"status": "committed", "journal_path": journal_file, "detail": ""}
            if all_original:
                journal["state"] = "ROLLED_BACK"
                journal["finished_at"] = int(time.time())
                journal["rollback"] = "complete"
                _journal(base_dir, journal)
                return {"status": "rolled_back", "journal_path": journal_file, "detail": ""}
            journal["state"] = "ROLLING_BACK"
            _journal(base_dir, journal)
            errors = _rollback_entries(base_dir, journal, journal_file=journal_file)
            journal["state"] = "ROLLED_BACK" if not errors else "RECOVERY_REQUIRED"
            journal["finished_at"] = int(time.time())
            journal["rollback"] = "complete" if not errors else "failed: " + "; ".join(errors)[:2000]
            journal["error"] = "; ".join(errors)[:2000]
            _journal(base_dir, journal)
            return {
                "status": journal["state"].lower(),
                "journal_path": journal_file,
                "detail": journal["rollback"],
            }
    except Exception as exc:
        _log.warning("restore recovery failed: %s", exc)
        try:
            journal["state"] = "RECOVERY_REQUIRED"
            journal["error"] = str(exc)[:2000]
            _journal(base_dir, journal)
        except Exception:
            pass
        return {
            "status": "recovery_required",
            "journal_path": journal_file,
            "detail": str(exc),
        }


def _restore_plain(
    base_dir: str,
    backup_path: str,
    *,
    categories=None,
    confirm: bool = False,
    now: int | None = None,
    journal_backup: str | None = None,
    pre_restore_encrypted: bool = False,
    pre_restore_password: str | None = None,
    allow_plaintext_pre_restore: bool = False,
) -> RestoreResult:
    """Restore selected categories with durable per-file rollback artifacts."""
    if not confirm:
        raise RestoreError("Restore requires explicit confirmation.")
    try:
        selected = _selected(categories)
    except RestoreError as exc:
        return RestoreResult(ok=False, status="invalid_selection", error=str(exc))
    backup_source = os.path.abspath(journal_backup or backup_path)
    backup_sha = _sha256_file(backup_source)
    if not backup_sha:
        return RestoreResult(ok=False, status="rejected", error="The backup could not be read.")
    operation_id = uuid.uuid4().hex
    staging = os.path.join(base_dir, STAGING_RELPATH, operation_id)
    journal = {
        "kind": "mei.restore_journal",
        "version": JOURNAL_VERSION,
        "operation_id": operation_id,
        "backup": backup_source,
        "backup_sha256": backup_sha,
        "selected": sorted(selected) if selected is not None else list(ALL_GROUPS),
        "pre_restore_backup": "",
        "pre_restore_protection": "encrypted" if pre_restore_encrypted else "plaintext",
        "started_at": int(now if now is not None else time.time()),
        "finished_at": 0,
        "state": "PREPARING",
        "files": [],
        "error": "",
        "rollback": "",
    }
    journal_file = ""
    try:
        with profile_locked(base_dir):
            plan = _preview_plain(base_dir, backup_path, categories=selected)
            if not plan["ok"]:
                return RestoreResult(
                    ok=False, status="rejected", error=plan.get("error", "invalid backup")
                )
            if _sha256_file(backup_source) != backup_sha:
                return RestoreResult(
                    ok=False,
                    status="rejected",
                    error="The backup changed after it was selected; nothing was restored.",
                )
            rows = [row for row in plan["files"] if row.get("changed")]
            if not rows:
                return RestoreResult(
                    ok=False,
                    status="unchanged",
                    error="Nothing in this backup differs from the profile.",
                )
            journal_file = _journal(base_dir, journal)
            pre, protection = _create_pre_restore(
                base_dir,
                now=now,
                encrypted=pre_restore_encrypted,
                password=pre_restore_password,
                allow_plaintext=allow_plaintext_pre_restore,
            )
            if not pre.ok:
                journal["state"] = "FAILED"
                journal["finished_at"] = int(time.time())
                journal["error"] = pre.error or "pre-restore snapshot failed"
                journal["rollback"] = "not_started"
                _journal(base_dir, journal)
                return RestoreResult(
                    ok=False,
                    status="blocked",
                    error=f"Could not create the pre-restore snapshot: {pre.error}",
                    journal_path=journal_file,
                    pre_restore_protection=protection,
                )
            journal["pre_restore_backup"] = pre.path
            journal["pre_restore_protection"] = protection
            journal["state"] = "SNAPSHOT_CREATED"
            _journal(base_dir, journal)
            staged_root = os.path.join(staging, "staged")
            rollback_root = os.path.join(staging, "rollback")
            os.makedirs(staged_root, mode=0o700, exist_ok=True)
            os.makedirs(rollback_root, mode=0o700, exist_ok=True)
            try:
                os.chmod(staging, 0o700)
            except OSError:
                pass
            extracted = _extract_selected(backup_path, staged_root, rows)
            entries: list[dict] = []
            for row in rows:
                arcname = str(row["path"])
                target = safe_child_path(base_dir, arcname)
                if not target:
                    raise RestoreError(f"Unsafe restore path: {arcname}")
                with open(extracted[arcname], "rb") as handle:
                    data = handle.read()
                _validate_payload(arcname, data)
                data = _prepare_restore_data(base_dir, arcname, data)
                staged_path = extracted[arcname]
                _write_bytes_atomic(staged_path, data)
                staged_sha = _sha256_file(staged_path)
                if not staged_sha:
                    raise RestoreError(f"Could not hash staged file {arcname}")
                original_exists = os.path.isfile(target)
                original_sha = _sha256_file(target) if original_exists else ""
                rollback_rel = ""
                if original_exists:
                    rollback_path = safe_child_path(rollback_root, arcname)
                    if not rollback_path:
                        raise RestoreError("Could not stage a rollback copy.")
                    with open(target, "rb") as handle:
                        original = handle.read()
                    _write_bytes_atomic(rollback_path, original)
                    if _sha256_file(rollback_path) != original_sha:
                        raise RestoreError(f"Rollback copy verification failed for {arcname}")
                    rollback_rel = "rollback/" + arcname.replace("\\", "/")
                entries.append(
                    {
                        "path": arcname,
                        "staged": "staged/" + arcname.replace("\\", "/"),
                        "rollback": rollback_rel,
                        "original_exists": original_exists,
                        "original_sha": original_sha,
                        "staged_sha": staged_sha,
                        "status": "STAGED",
                    }
                )
            journal["files"] = entries
            journal["state"] = "STAGED"
            _journal(base_dir, journal)
            journal["state"] = "APPLYING"
            _journal(base_dir, journal)
            for entry in entries:
                target = _safe_target(base_dir, entry)
                original_exists = bool(entry["original_exists"])
                state, _probe = _classify_target(target, entry)
                if original_exists:
                    if state != TARGET_ORIGINAL:
                        raise RestoreError(
                            f"{entry['path']} changed or became unreadable while the restore was being prepared; refusing to overwrite it."
                        )
                elif state != TARGET_MISSING:
                    raise RestoreError(
                        f"{entry['path']} appeared while the restore was being prepared; refusing to overwrite it."
                    )
                staged_path = _safe_staged(staging, entry)
                if _sha256_file(staged_path) != entry["staged_sha"]:
                    raise RestoreError(f"Staged bytes changed for {entry['path']}")
                entry["status"] = "APPLYING"
                _journal(base_dir, journal)
                with open(staged_path, "rb") as handle:
                    data = handle.read()
                _write_bytes_atomic(target, data)
                entry["status"] = "APPLIED"
                entry["applied_sha"] = _sha256_file(target)
                _journal(base_dir, journal)
            journal["state"] = "VERIFYING"
            _journal(base_dir, journal)
            for entry in entries:
                target = _safe_target(base_dir, entry)
                if _sha256_file(target) != entry["staged_sha"]:
                    raise RestoreError(f"Post-restore verification failed for {entry['path']}")
                if str(entry["path"]).endswith(".json"):
                    with open(target, "rb") as handle:
                        _validate_payload(str(entry["path"]), handle.read())
            journal["state"] = "COMMITTED"
            journal["finished_at"] = int(time.time())
            journal["rollback"] = ""
            _journal(base_dir, journal)
        shutil.rmtree(staging, ignore_errors=True)
        return RestoreResult(
            ok=True,
            status="restored",
            restored=[str(row["path"]) for row in rows],
            skipped=plan.get("warnings", []),
            pre_restore_backup=pre.path,
            journal_path=journal_file,
            rollback="",
            pre_restore_protection=protection,
        )
    except Exception as exc:
        rollback_error = ""
        try:
            journal["state"] = "ROLLING_BACK"
            if journal_file:
                _journal(base_dir, journal)
            errors = _rollback_entries(base_dir, journal, journal_file=journal_file)
            rollback_error = "; ".join(errors)
            journal["state"] = "RECOVERY_REQUIRED" if errors else "ROLLED_BACK"
            journal["finished_at"] = int(time.time())
            journal["error"] = str(exc)[:2000]
            journal["rollback"] = "complete" if not errors else f"failed: {rollback_error[:1000]}"
            if journal_file:
                _journal(base_dir, journal)
        except Exception as rollback_exc:
            rollback_error = str(rollback_exc)
            try:
                journal["state"] = "RECOVERY_REQUIRED"
                journal["error"] = str(exc)[:2000]
                journal["rollback"] = f"failed: {rollback_error[:1000]}"
                if journal_file:
                    _journal(base_dir, journal)
            except Exception:
                pass
        _log.warning("restore %s failed: %s", operation_id, exc)
        return RestoreResult(
            ok=False,
            status="recovery_required" if rollback_error else "failed",
            error=str(exc),
            pre_restore_backup=str(journal.get("pre_restore_backup") or ""),
            journal_path=journal_file,
            rollback=journal.get("rollback", ""),
            pre_restore_protection=str(journal.get("pre_restore_protection") or ""),
        )


def restore(
    base_dir: str,
    backup_path: str,
    *,
    categories=None,
    confirm: bool = False,
    now: int | None = None,
    password: str | None = None,
    pre_restore_encrypted: bool = True,
    pre_restore_password: str | None = None,
    allow_plaintext_pre_restore: bool = False,
) -> RestoreResult:
    """Restore a plain or encrypted backup without a confidentiality downgrade."""
    from litebrowser.services import encrypted_backup_service

    if not encrypted_backup_service.is_encrypted(backup_path):
        return _restore_plain(
            base_dir,
            backup_path,
            categories=categories,
            confirm=confirm,
            now=now,
            pre_restore_encrypted=False,
            allow_plaintext_pre_restore=True,
        )
    if not password:
        return RestoreResult(
            ok=False,
            status="password_required",
            error="This backup is encrypted; enter its password.",
        )
    if not pre_restore_encrypted and not allow_plaintext_pre_restore:
        return RestoreResult(
            ok=False,
            status="blocked",
            error="This encrypted backup cannot silently create a plaintext pre-restore snapshot.",
        )
    try:
        with encrypted_backup_service.materialized(backup_path, password) as plain:
            return _restore_plain(
                base_dir,
                plain,
                categories=categories,
                confirm=confirm,
                now=now,
                journal_backup=backup_path,
                pre_restore_encrypted=pre_restore_encrypted,
                pre_restore_password=pre_restore_password or password,
                allow_plaintext_pre_restore=allow_plaintext_pre_restore,
            )
    except encrypted_backup_service.EncryptedBackupError as exc:
        return RestoreResult(ok=False, status=exc.status, error=str(exc))


def inventory(destination: str) -> list[dict]:
    return backup_service.list_backups(destination, verify=False)


__all__ = [
    "ALL_GROUPS",
    "JOURNAL_RELPATH",
    "JOURNAL_VERSION",
    "RestoreError",
    "RestoreResult",
    "inventory",
    "journal_path",
    "preview",
    "recover_interrupted",
    "restore",
]
