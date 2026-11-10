"""Staged profile restore with a pre-restore snapshot and rollback.

Restore is a filesystem operation across several stores, so it is not one atomic
transaction.  The journal records the intended files and the rollback copies
before anything is replaced.  On failure the previous bytes are written back;
if rollback itself cannot complete, the result says ``RECOVERY_REQUIRED``
instead of pretending the profile is intact.

Credentials are never in a backup (``backup_service`` excludes them), so a
restore cannot roll back a newly signed-in secret to an older value.
"""
from __future__ import annotations

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
MAX_MEMBER_BYTES = backup_service.MAX_FILE_BYTES
MAX_TOTAL_BYTES = backup_service.MAX_TOTAL_BYTES
NOTES_PREFIX = "SafeVault/notes/"
ALL_GROUPS = tuple(sorted(set(RESTORE_GROUPS) | {"notes"}))


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
        }


def journal_path(base_dir: str) -> str:
    return os.path.join(base_dir, JOURNAL_RELPATH)


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
    if categories is None:
        return None
    if isinstance(categories, str):
        categories = [categories]
    result = {str(item) for item in categories if str(item).strip()}
    unknown = result - set(ALL_GROUPS)
    if unknown:
        raise RestoreError("Unknown restore category: " + ", ".join(sorted(unknown)))
    return result or None


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
                    version = int(payload.get("schema_version" if path == "prefs.json" else "version", 1) or 1)
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

    if not encrypted_backup_service.is_encrypted(backup_path):
        return _preview_plain(base_dir, backup_path, categories=categories)
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
        for row in files:
            arcname = str(row["path"])
            member = archive.getinfo(arcname)
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
                shutil.copyfileobj(source, handle, 1024 * 1024)
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
        version = int(payload.get("schema_version", app_paths.APP_SCHEMA_VERSION) or 0) if isinstance(payload, dict) else 0
    elif path == "profile_meta.json":
        expected = app_paths.APP_SCHEMA_VERSION
        version = int(payload.get("schema_version", app_paths.APP_SCHEMA_VERSION) or 0) if isinstance(payload, dict) else 0
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
    write_json(path, data)
    return path


def _restore_plain(
    base_dir: str,
    backup_path: str,
    *,
    categories=None,
    confirm: bool = False,
    now: int | None = None,
    journal_backup: str | None = None,
) -> RestoreResult:
    """Restore selected categories, preserving the pre-restore state."""
    if not confirm:
        raise RestoreError("Restore requires explicit confirmation.")
    selected = _selected(categories)
    plan = _preview_plain(base_dir, backup_path, categories=selected)
    if not plan["ok"]:
        return RestoreResult(ok=False, status="rejected", error=plan.get("error", "invalid backup"))
    rows = [row for row in plan["files"] if row.get("changed")]
    if not rows:
        return RestoreResult(ok=False, status="unchanged", error="Nothing in this backup differs from the profile.")

    pre = backup_service.create_backup(base_dir, kind="pre-restore", now=now)
    if not pre.ok:
        return RestoreResult(
            ok=False,
            status="blocked",
            error=f"Could not create the pre-restore snapshot: {pre.error}",
        )

    operation_id = uuid.uuid4().hex
    staging = os.path.join(base_dir, STAGING_RELPATH, operation_id)
    rollback_dir = os.path.join(staging, "rollback")
    os.makedirs(rollback_dir, exist_ok=True)
    journal = {
        "kind": "mei.restore_journal",
        "version": 1,
        "operation_id": operation_id,
        "backup": os.path.abspath(journal_backup or backup_path),
        "pre_restore_backup": pre.path,
        "started_at": int(now or time.time()),
        "finished_at": 0,
        "state": "PREPARING",
        "files": [],
        "error": "",
        "rollback": "",
    }
    journal_file = _journal(base_dir, journal)
    originals: dict[str, bytes | None] = {}
    written: list[str] = []
    try:
        with profile_locked(base_dir):
            extracted = _extract_selected(backup_path, staging, rows)
            for row in rows:
                arcname = str(row["path"])
                with open(extracted[arcname], "rb") as handle:
                    data = handle.read()
                _validate_payload(arcname, data)
                data = _prepare_restore_data(base_dir, arcname, data)
                with open(extracted[arcname], "wb") as handle:
                    handle.write(data)
            journal["state"] = "APPLYING"
            journal["files"] = [row["path"] for row in rows]
            _journal(base_dir, journal)
            for row in rows:
                arcname = str(row["path"])
                target = safe_child_path(base_dir, arcname)
                if not target:
                    raise RestoreError(f"Unsafe restore path: {arcname}")
                original = None
                if os.path.isfile(target):
                    with open(target, "rb") as handle:
                        original = handle.read()
                originals[target] = original
                if original is not None:
                    copy_path = safe_child_path(rollback_dir, arcname)
                    if not copy_path:
                        raise RestoreError("Could not stage a rollback copy.")
                    os.makedirs(os.path.dirname(copy_path), exist_ok=True)
                    _write_bytes_atomic(copy_path, original)
                with open(extracted[arcname], "rb") as handle:
                    data = handle.read()
                _write_bytes_atomic(target, data)
                written.append(target)
            for row in rows:
                if str(row["path"]).endswith(".json"):
                    target = safe_child_path(base_dir, str(row["path"]))
                    with open(target, "rb") as handle:
                        _validate_payload(str(row["path"]), handle.read())
            journal["state"] = "COMMITTED"
            journal["finished_at"] = int(time.time())
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
        )
    except Exception as exc:
        rollback_error = ""
        try:
            for target in reversed(written):
                original = originals.get(target)
                if original is None:
                    if os.path.exists(target):
                        os.remove(target)
                else:
                    _write_bytes_atomic(target, original)
        except Exception as rollback_exc:
            rollback_error = str(rollback_exc)
        journal["state"] = "RECOVERY_REQUIRED" if rollback_error else "FAILED"
        journal["finished_at"] = int(time.time())
        journal["error"] = str(exc)[:2000]
        journal["rollback"] = "complete" if not rollback_error else f"failed: {rollback_error[:1000]}"
        try:
            _journal(base_dir, journal)
        except Exception:
            pass
        _log.warning("restore %s failed: %s", operation_id, exc)
        return RestoreResult(
            ok=False,
            status="recovery_required" if rollback_error else "failed",
            error=str(exc),
            pre_restore_backup=pre.path,
            journal_path=journal_file,
            rollback=journal["rollback"],
        )


def restore(
    base_dir: str,
    backup_path: str,
    *,
    categories=None,
    confirm: bool = False,
    now: int | None = None,
    password: str | None = None,
) -> RestoreResult:
    """Restore a plain or encrypted backup, preserving the pre-restore state."""
    from litebrowser.services import encrypted_backup_service

    if not encrypted_backup_service.is_encrypted(backup_path):
        return _restore_plain(
            base_dir, backup_path, categories=categories, confirm=confirm, now=now
        )
    if not password:
        return RestoreResult(
            ok=False,
            status="password_required",
            error="This backup is encrypted; enter its password.",
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
            )
    except encrypted_backup_service.EncryptedBackupError as exc:
        return RestoreResult(ok=False, status=exc.status, error=str(exc))


def inventory(destination: str) -> list[dict]:
    return backup_service.list_backups(destination, verify=False)


__all__ = [
    "ALL_GROUPS",
    "JOURNAL_RELPATH",
    "RestoreError",
    "RestoreResult",
    "inventory",
    "journal_path",
    "preview",
    "restore",
]
