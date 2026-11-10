"""Versioned, independently verifiable profile backups.

A backup is a zip with a manifest that lists every included file, its category,
size and SHA-256.  The archive is built in a sibling ``.part`` file, verified by
re-opening it and checking the manifest, and only then atomically renamed to its
final name.  An incomplete archive therefore never looks like a successful
backup.

Scope is an explicit allowlist (``core/storage_catalog``).  Credentials, the
secret store, Chromium profile data, caches, downloads, quarantine artifacts and
proxy configuration are excluded.  Preferences are scrubbed for secret-shaped
keys before they are written, because a profile zip is support data users copy
and email.

The default destination is a sibling of the active profile
(``<profiles>/Mei Backups/<profile>``), so losing the profile directory does not
also lose its backups.  A user-selected destination is accepted only when it is
outside the profile.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field

from litebrowser.core import prefs, storage_health
from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_catalog import STORES, StoreDescriptor
from litebrowser.core.storage_utils import _atomic_replace, write_json

_log = get_logger("backup_service")

FORMAT_VERSION = 1
MANIFEST_NAME = "mei-backup-manifest.json"
EXTENSION = ".mei-backup.zip"
ENCRYPTED_EXTENSION = ".mei-backup.enc"
ENCRYPTED_MAGIC = b"MEIENC01"
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_DAILY_KEEP = 7
DEFAULT_WEEKLY_KEEP = 4
DEFAULT_MONTHLY_KEEP = 6
DEFAULT_FREQUENCY = "daily"

_SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "authorization",
        "bearer",
        "private_key",
        "proxy_password",
    }
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_REDACTED = "[redacted by Mei backup]"
_CREATE_LOCK = threading.Lock()


class BackupError(OSError):
    """A backup could not be created or verified safely."""


@dataclass(frozen=True)
class BackupPolicy:
    destination: str
    enabled: bool = True
    frequency: str = DEFAULT_FREQUENCY
    daily_keep: int = DEFAULT_DAILY_KEEP
    weekly_keep: int = DEFAULT_WEEKLY_KEEP
    monthly_keep: int = DEFAULT_MONTHLY_KEEP

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "enabled": self.enabled,
            "frequency": self.frequency,
            "daily_keep": self.daily_keep,
            "weekly_keep": self.weekly_keep,
            "monthly_keep": self.monthly_keep,
        }


@dataclass
class BackupResult:
    ok: bool
    path: str = ""
    manifest: dict = field(default_factory=dict)
    error: str = ""
    verification: dict = field(default_factory=dict)
    encrypted: bool = False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "path": self.path,
            "manifest": self.manifest,
            "error": self.error,
            "verification": self.verification,
            "encrypted": self.encrypted,
        }


def _app_version() -> str:
    from litebrowser.core import app_version

    for name in ("VERSION", "APP_VERSION", "__version__"):
        value = getattr(app_version, name, "")
        if value:
            return str(value)
    return "unknown"


def _now(now: int | None = None) -> int:
    return int(now if now is not None else time.time())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _profile_id(base_dir: str) -> str:
    return _sha256(os.path.normcase(os.path.realpath(base_dir)).encode("utf-8"))[:16]


def default_destination(base_dir: str) -> str:
    profile = os.path.basename(os.path.normpath(base_dir)) or "profile"
    parent = os.path.dirname(os.path.normpath(base_dir))
    return os.path.join(parent, "Mei Backups", profile)


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def destination_is_separate(base_dir: str, destination: str) -> bool:
    """True only when a backup destination is outside the active profile."""
    try:
        profile = _real(base_dir)
        target = _real(destination)
        if target == profile:
            return False
        return os.path.commonpath([profile, target]) != profile
    except (OSError, ValueError):
        return False


def load_policy(base_dir: str) -> BackupPolicy:
    raw = prefs.get_pref(base_dir, "backup_policy", {})
    raw = raw if isinstance(raw, dict) else {}
    destination = str(raw.get("destination") or "").strip() or default_destination(base_dir)
    frequency = str(raw.get("frequency") or DEFAULT_FREQUENCY).lower()
    if frequency not in ("manual", "daily", "weekly"):
        frequency = DEFAULT_FREQUENCY

    def keep(key: str, default: int, maximum: int) -> int:
        try:
            return max(1, min(maximum, int(raw.get(key, default))))
        except (TypeError, ValueError, OverflowError):
            return default

    return BackupPolicy(
        destination=destination,
        enabled=bool(raw.get("enabled", True)),
        frequency=frequency,
        daily_keep=keep("daily_keep", DEFAULT_DAILY_KEEP, 90),
        weekly_keep=keep("weekly_keep", DEFAULT_WEEKLY_KEEP, 52),
        monthly_keep=keep("monthly_keep", DEFAULT_MONTHLY_KEEP, 60),
    )


def save_policy(base_dir: str, policy: BackupPolicy) -> None:
    prefs.save_pref(base_dir, "backup_policy", policy.as_dict())


def _redact(value, redacted: list[str]):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                result[key] = _REDACTED
                redacted.append(str(key))
            else:
                result[key] = _redact(item, redacted)
        return result
    if isinstance(value, list):
        return [_redact(item, redacted) for item in value]
    return value


def _read_store_bytes(path: str, descriptor: StoreDescriptor, redacted: list[str]) -> bytes:
    result = storage_health.read_json_checked(path, dict if descriptor.root == "dict" else list)
    if not result.ok:
        raise BackupError(
            f"{descriptor.name} is unreadable ({result.status}); fix or restore it before backing up"
        )
    if descriptor.name == "prefs.json":
        payload = _redact(result.value, redacted)
        return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with open(path, "rb") as handle:
        return handle.read()


@dataclass(frozen=True)
class _Item:
    arcname: str
    category: str
    data: bytes

    @property
    def sha256(self) -> str:
        return _sha256(self.data)


def _note_items(base_dir: str, excluded: list[str]) -> list[_Item]:
    root = os.path.join(base_dir, "SafeVault", "notes")
    if not os.path.isdir(root):
        return []
    items = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not os.path.islink(os.path.join(current, name)))
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path):
                excluded.append(f"SafeVault/notes symlink skipped: {name}")
                continue
            if not name.lower().endswith((".md", ".txt")):
                continue
            try:
                size = os.path.getsize(path)
                if size > MAX_FILE_BYTES:
                    raise BackupError(f"note is too large to back up: {name}")
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError as exc:
                raise BackupError(f"could not read note {name}: {exc}") from exc
            relative = os.path.relpath(path, base_dir).replace("\\", "/")
            items.append(_Item(relative, "notes", data))
    return items


def _collect(base_dir: str) -> tuple[list[_Item], dict, list[str]]:
    items: list[_Item] = []
    excluded: list[str] = []
    redacted: list[str] = []
    schemas: dict[str, int] = {}
    total = 0
    with profile_locked(base_dir):
        for descriptor in STORES:
            path = os.path.join(base_dir, descriptor.name)
            if not os.path.isfile(path):
                continue
            try:
                data = _read_store_bytes(path, descriptor, redacted)
            except BackupError:
                raise
            except OSError as exc:
                raise BackupError(f"could not read {descriptor.name}: {exc}") from exc
            if len(data) > MAX_FILE_BYTES:
                raise BackupError(f"{descriptor.name} is too large to back up")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise BackupError("the profile is larger than the backup limit")
            items.append(_Item(descriptor.name, descriptor.category, data))
            try:
                parsed = json.loads(data.decode("utf-8"))
                if isinstance(parsed, dict) and isinstance(parsed.get(descriptor.version_key), int):
                    schemas[descriptor.name] = int(parsed[descriptor.version_key])
            except (ValueError, UnicodeError):
                pass
        notes = _note_items(base_dir, excluded)
        items.extend(notes)
        total += sum(len(item.data) for item in notes)
        if total > MAX_TOTAL_BYTES:
            raise BackupError("the profile is larger than the backup limit")
    if redacted:
        excluded.append(
            "prefs secret-shaped keys redacted: " + ", ".join(sorted(set(redacted)))[:500]
        )
    return items, schemas, excluded


def _manifest(
    base_dir: str,
    backup_id: str,
    kind: str,
    created_at: int,
    items: list[_Item],
    schemas: dict,
    excluded: list[str],
) -> dict:
    categories = sorted({item.category for item in items})
    return {
        "kind": "mei.profile_backup",
        "format_version": FORMAT_VERSION,
        "backup_id": backup_id,
        "kind_detail": kind,
        "created_at": created_at,
        "mei_version": _app_version(),
        "profile_id": _profile_id(base_dir),
        "status": "complete",
        "included_categories": categories,
        "excluded": excluded,
        "schemas": schemas,
        "files": [
            {
                "path": item.arcname,
                "category": item.category,
                "size": len(item.data),
                "sha256": item.sha256,
            }
            for item in items
        ],
        "total_bytes": sum(len(item.data) for item in items),
    }


def _safe_arcname(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or ":" in normalized:
        return False
    parts = normalized.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def verify_backup(path: str) -> dict:
    """Re-open a backup and verify its manifest, paths, sizes and checksums."""
    result = {"ok": False, "status": "corrupt", "errors": [], "manifest": {}, "path": path}
    if not os.path.isfile(path):
        result["errors"].append("backup file does not exist")
        return result
    try:
        with open(path, "rb") as handle:
            encrypted = handle.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC
    except OSError:
        encrypted = False
    if encrypted:
        result["encrypted"] = True
        result["status"] = "encrypted"
        result["errors"].append("This backup is encrypted; a password is required.")
        return result
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if MANIFEST_NAME not in archive.namelist():
                result["errors"].append("manifest is missing")
                return result
            info = archive.getinfo(MANIFEST_NAME)
            if info.file_size > 8 * 1024 * 1024:
                result["errors"].append("manifest is too large")
                return result
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("kind") != "mei.profile_backup":
                result["errors"].append("manifest kind is not a Mei profile backup")
                return result
            if int(manifest.get("format_version") or 0) > FORMAT_VERSION:
                result["errors"].append("backup format is newer than this build")
                result["status"] = "incompatible"
                return result
            if manifest.get("status") != "complete":
                result["status"] = "incomplete"
                result["errors"].append("backup did not reach complete status")
                return result
            rows = manifest.get("files")
            if not isinstance(rows, list):
                result["errors"].append("manifest has no file list")
                return result
            listed = set()
            total = 0
            for row in rows:
                if not isinstance(row, dict):
                    result["errors"].append("manifest file entry is malformed")
                    break
                arcname = str(row.get("path") or "")
                if not _safe_arcname(arcname) or arcname == MANIFEST_NAME:
                    result["errors"].append(f"unsafe archive path: {arcname!r}")
                    break
                if arcname in listed:
                    result["errors"].append(f"duplicate archive path: {arcname}")
                    break
                listed.add(arcname)
                try:
                    member = archive.getinfo(arcname)
                except KeyError:
                    result["errors"].append(f"missing archive member: {arcname}")
                    break
                if _zip_member_is_symlink(member):
                    result["errors"].append(f"symlink is not allowed: {arcname}")
                    break
                declared_size = int(row.get("size") or 0)
                if member.file_size != declared_size or member.file_size > MAX_FILE_BYTES:
                    result["errors"].append(f"size mismatch: {arcname}")
                    break
                total += member.file_size
                if total > MAX_TOTAL_BYTES:
                    result["errors"].append("archive expands beyond the backup limit")
                    break
                digest = hashlib.sha256()
                with archive.open(member) as handle:
                    while True:
                        block = handle.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                if digest.hexdigest() != str(row.get("sha256") or ""):
                    result["errors"].append(f"checksum mismatch: {arcname}")
                    break
            extras = set(archive.namelist()) - listed - {MANIFEST_NAME}
            if extras and not result["errors"]:
                result["errors"].append("archive contains files not listed in the manifest")
            if result["errors"]:
                return result
            result.update(
                {
                    "ok": True,
                    "status": "verified",
                    "manifest": manifest,
                    "archive": os.path.abspath(path),
                }
            )
            return result
    except (OSError, zipfile.BadZipFile, ValueError, UnicodeError, KeyError) as exc:
        result["errors"].append(f"backup could not be opened: {exc}")
        return result


def _write_part(archive_path: str, manifest: dict, items: list[_Item]) -> None:
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for item in items:
            archive.writestr(item.arcname, item.data)
    with open(archive_path, "r+b") as handle:
        os.fsync(handle.fileno())


def create_backup(
    base_dir: str,
    *,
    destination: str | None = None,
    kind: str = "manual",
    now: int | None = None,
) -> BackupResult:
    """Create and verify one backup, returning the exact artifact path."""
    # Manual, scheduled and pre-restore calls can arrive from different
    # workers.  Only one archive may be collected/written at a time; a second
    # caller gets an explicit result instead of racing the first one.
    if not _CREATE_LOCK.acquire(blocking=False):
        return BackupResult(ok=False, error="Another backup is already in progress.")
    try:
        return _create_backup_locked(
            base_dir, destination=destination, kind=kind, now=now
        )
    finally:
        _CREATE_LOCK.release()


def _create_backup_locked(
    base_dir: str,
    *,
    destination: str | None = None,
    kind: str = "manual",
    now: int | None = None,
) -> BackupResult:
    policy = load_policy(base_dir)
    target_dir = os.path.abspath(destination or policy.destination)
    if not destination_is_separate(base_dir, target_dir):
        return BackupResult(
            ok=False,
            error="The backup destination must be outside the active profile.",
        )
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        return BackupResult(ok=False, error=f"Could not create the backup folder: {exc}")
    try:
        items, schemas, excluded = _collect(base_dir)
    except (BackupError, OSError) as exc:
        return BackupResult(ok=False, error=str(exc))

    created = _now(now)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(created))
    backup_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    safe_kind = _SAFE_NAME.sub("-", kind).strip("-")[:24] or "manual"
    filename = f"mei-{safe_kind}-{backup_id}{EXTENSION}"
    final_path = os.path.join(target_dir, filename)
    part_path = os.path.join(target_dir, "." + filename + ".part")
    manifest = _manifest(base_dir, backup_id, safe_kind, created, items, schemas, excluded)
    try:
        _write_part(part_path, manifest, items)
        verification = verify_backup(part_path)
        if not verification["ok"]:
            failed_path = os.path.join(target_dir, "." + filename + ".failed")
            try:
                os.replace(part_path, failed_path)
            except OSError:
                pass
            return BackupResult(
                ok=False,
                error="Backup verification failed; no completed backup was published.",
                verification=verification,
            )
        _atomic_replace(part_path, final_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        try:
            if os.path.exists(part_path):
                os.unlink(part_path)
        except OSError:
            pass
        return BackupResult(ok=False, error=f"Backup failed: {exc}")
    _log.info("backup %s created (%d files)", filename, len(items))
    return BackupResult(ok=True, path=final_path, manifest=manifest, verification=verification)


def _backup_created(path: str) -> int:
    verification = verify_backup(path)
    if verification["ok"]:
        return int(verification["manifest"].get("created_at") or 0)
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def list_backups(destination: str, *, verify: bool = False) -> list[dict]:
    if not destination or not os.path.isdir(destination):
        return []
    rows = []
    for name in sorted(os.listdir(destination)):
        encrypted = name.endswith(ENCRYPTED_EXTENSION)
        if (not name.endswith(EXTENSION) and not encrypted) or name.startswith("."):
            continue
        path = os.path.join(destination, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        row = {
            "path": path,
            "name": name,
            "size": stat.st_size,
            "modified_at": int(stat.st_mtime),
            "created_at": int(stat.st_mtime),
            "status": "unverified",
            "verified": False,
            "encrypted": encrypted,
        }
        if encrypted:
            from litebrowser.services import encrypted_backup_service

            inspected = encrypted_backup_service.inspect(path)
            row.update(
                {
                    "status": inspected["status"] if inspected.get("ok") else "invalid_encrypted",
                    "verified": False,
                    "errors": [
                        inspected.get("error") or "Encrypted backup requires a password for verification."
                    ],
                    "created_at": int(inspected.get("created_at") or 0),
                    "encrypted_header": inspected.get("header") or {},
                }
            )
            rows.append(row)
            continue
        if verify:
            checked = verify_backup(path)
            row.update(
                {
                    "status": checked["status"],
                    "verified": bool(checked["ok"]),
                    "errors": checked["errors"],
                    "manifest": checked["manifest"],
                }
            )
            if checked["ok"]:
                row["created_at"] = int(checked["manifest"].get("created_at") or 0)
        else:
            checked = verify_backup(path)
            if checked["ok"]:
                row.update(
                    {
                        "status": "verified",
                        "verified": True,
                        "manifest": checked["manifest"],
                        "created_at": int(checked["manifest"].get("created_at") or 0),
                    }
                )
            else:
                row.update({"status": checked["status"], "errors": checked["errors"]})
        rows.append(row)
    rows.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return rows


def _month_key(timestamp: int) -> str:
    return time.strftime("%Y-%m", time.gmtime(timestamp))


def _week_key(timestamp: int) -> str:
    year, week, _day = time.gmtime(timestamp)[:3]
    return f"{year}-{week:02d}"


def apply_retention(destination: str, policy: BackupPolicy, *, now: int | None = None) -> list[str]:
    """Delete only old *verified* backups, never the newest/last copy.

    Keeps the newest ``daily_keep`` archives, then one archive per ISO week for
    ``weekly_keep`` weeks, then one per month for ``monthly_keep`` months.  Any
    unverified or incomplete file is left alone for the user to inspect.
    """
    # Encrypted rows are deliberately not deleted: without the password this
    # process cannot verify them, and a retention pass must never guess.
    rows = [row for row in list_backups(destination, verify=True) if row.get("verified")]
    if len(rows) <= 1:
        return []
    now = _now(now)
    keep: set[str] = set()
    keep.add(rows[0]["path"])
    for row in rows[: max(1, policy.daily_keep)]:
        if now - int(row["created_at"]) <= 2 * 86400 or len(keep) <= policy.daily_keep:
            keep.add(row["path"])
    weeks: dict[str, str] = {}
    for row in rows:
        if len(weeks) >= max(1, policy.weekly_keep):
            break
        key = _week_key(int(row["created_at"]))
        if key not in weeks:
            weeks[key] = row["path"]
            keep.add(row["path"])
    months: dict[str, str] = {}
    for row in rows:
        if len(months) >= max(1, policy.monthly_keep):
            break
        key = _month_key(int(row["created_at"]))
        if key not in months:
            months[key] = row["path"]
            keep.add(row["path"])
    deleted = []
    for row in rows:
        if row["path"] in keep:
            continue
        try:
            os.unlink(row["path"])
            deleted.append(row["path"])
        except OSError as exc:
            _log.warning("could not remove old backup %s: %s", row["name"], exc)
    return deleted


def due_for_backup(base_dir: str, *, now: int | None = None) -> bool:
    policy = load_policy(base_dir)
    if not policy.enabled or policy.frequency == "manual":
        return False
    rows = list_backups(policy.destination, verify=False)
    if not rows:
        return True
    interval = 7 * 86400 if policy.frequency == "weekly" else 86400
    return _now(now) - int(rows[0].get("created_at") or 0) >= interval


def status(base_dir: str) -> dict:
    policy = load_policy(base_dir)
    rows = list_backups(policy.destination, verify=False)
    last = rows[0] if rows else {}
    return {
        "enabled": policy.enabled,
        "destination": policy.destination,
        "destination_exists": os.path.isdir(policy.destination),
        "destination_separate": destination_is_separate(base_dir, policy.destination),
        "frequency": policy.frequency,
        "retention": {
            "daily": policy.daily_keep,
            "weekly": policy.weekly_keep,
            "monthly": policy.monthly_keep,
        },
        "backup_count": len(rows),
        "last_backup": last,
        "last_backup_at": int(last.get("created_at") or 0),
        "due": due_for_backup(base_dir),
        "secret_store_excluded": True,
        "incognito_excluded": True,
        "encrypted_count": sum(1 for row in rows if row.get("encrypted")),
    }


def write_manifest_sidecar(path: str) -> str:
    """Write a human-readable manifest next to a backup (never a secret)."""
    checked = verify_backup(path)
    if not checked["ok"]:
        raise BackupError("cannot write a manifest for an invalid backup")
    sidecar = path + ".manifest.json"
    write_json(sidecar, checked["manifest"])
    return sidecar


__all__ = [
    "BackupError",
    "BackupPolicy",
    "BackupResult",
    "DEFAULT_DAILY_KEEP",
    "DEFAULT_FREQUENCY",
    "DEFAULT_MONTHLY_KEEP",
    "DEFAULT_WEEKLY_KEEP",
    "EXTENSION",
    "ENCRYPTED_EXTENSION",
    "ENCRYPTED_MAGIC",
    "FORMAT_VERSION",
    "MANIFEST_NAME",
    "apply_retention",
    "create_backup",
    "default_destination",
    "destination_is_separate",
    "due_for_backup",
    "list_backups",
    "load_policy",
    "save_policy",
    "status",
    "verify_backup",
    "write_manifest_sidecar",
]
