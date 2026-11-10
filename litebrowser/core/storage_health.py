"""Damage-aware storage primitives.

The rest of the application used to treat every failed read as an empty store:
``read_json(path, default)`` logged a warning and returned the default, so the
next save replaced bytes that might still contain recoverable user data.

This module makes the distinction explicit:

* missing file (a legitimate first run),
* intentionally empty file,
* oversized file (refused before it is loaded),
* unreadable file (permissions/lock),
* invalid UTF-8,
* malformed JSON,
* valid JSON with the wrong root shape.

Nothing here deletes or rewrites the original.  :func:`quarantine_file` keeps a
byte-for-byte copy under ``<profile>/Recovery/quarantine`` with a checksum and a
sidecar report, so a later recovery or support session can inspect exactly what
Mei saw.  Quarantine names are collision-resistant and never overwrite an
earlier artifact.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from litebrowser.core.log import get_logger
from litebrowser.core.storage_catalog import STORES
from litebrowser.core.storage_utils import _atomic_replace, tempfile_mkstemp_same_dir

_log = get_logger("storage_health")

RECOVERY_DIR = "Recovery"
QUARANTINE_DIR = os.path.join(RECOVERY_DIR, "quarantine")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_QUARANTINE_BYTES = 256 * 1024 * 1024

#: Read statuses.  They are deliberately strings so a report can be serialised
#: without importing this module.
STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_EMPTY = "empty"
STATUS_TOO_LARGE = "too_large"
STATUS_UNREADABLE = "unreadable"
STATUS_INVALID_ENCODING = "invalid_encoding"
STATUS_MALFORMED_JSON = "malformed_json"
STATUS_WRONG_ROOT = "wrong_root_type"


class StorageHealthError(OSError):
    """A storage artifact could not be inspected or preserved safely."""


@dataclass(frozen=True)
class JsonReadResult:
    """The outcome of reading one JSON file without guessing at its meaning."""

    path: str
    status: str
    value: Any = None
    size: int = 0
    sha256: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def corrupt(self) -> bool:
        return self.status in {
            STATUS_EMPTY,
            STATUS_TOO_LARGE,
            STATUS_UNREADABLE,
            STATUS_INVALID_ENCODING,
            STATUS_MALFORMED_JSON,
            STATUS_WRONG_ROOT,
        }

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "size": self.size,
            "sha256": self.sha256,
            "detail": self.detail,
        }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str, max_bytes: int = MAX_QUARANTINE_BYTES) -> str:
    """Hash a file without loading it whole, returning '' when too large."""
    digest = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                read += len(block)
                if read > max_bytes:
                    return ""
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def read_json_checked(
    path: str,
    expected_type: type | tuple[type, ...] | None = None,
    max_bytes: int = MAX_JSON_BYTES,
) -> JsonReadResult:
    """Read JSON and report *why* a read failed instead of returning a default.

    The file is opened once for metadata and once for bytes; the bytes are the
    ones hashed and parsed, so a concurrent writer cannot make the report
    describe a different generation than the one that was inspected.
    """
    if not os.path.isfile(path):
        return JsonReadResult(path=path, status=STATUS_MISSING)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return JsonReadResult(path=path, status=STATUS_UNREADABLE, detail=str(exc))
    if size == 0:
        return JsonReadResult(path=path, status=STATUS_EMPTY)
    if size > max_bytes:
        return JsonReadResult(
            path=path,
            status=STATUS_TOO_LARGE,
            size=size,
            detail=f"file is {size} bytes; the limit is {max_bytes}",
        )
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return JsonReadResult(path=path, status=STATUS_UNREADABLE, size=size, detail=str(exc))
    size = len(data)
    digest = _sha256_bytes(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return JsonReadResult(
            path=path,
            status=STATUS_INVALID_ENCODING,
            size=size,
            sha256=digest,
            detail=f"invalid UTF-8 at byte {exc.start}",
        )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return JsonReadResult(
            path=path,
            status=STATUS_MALFORMED_JSON,
            size=size,
            sha256=digest,
            detail=f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
    if expected_type is not None and not isinstance(value, expected_type):
        expected = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else "/".join(item.__name__ for item in expected_type)
        )
        return JsonReadResult(
            path=path,
            status=STATUS_WRONG_ROOT,
            value=value,
            size=size,
            sha256=digest,
            detail=f"root is {type(value).__name__}, expected {expected}",
        )
    return JsonReadResult(
        path=path,
        status=STATUS_OK,
        value=value,
        size=size,
        sha256=digest,
    )


def _inside(root: str, path: str) -> bool:
    try:
        root_real = os.path.normcase(os.path.realpath(root))
        target = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([root_real, target]) == root_real
    except (OSError, ValueError):
        return False


def _safe_fragment(value: str) -> str:
    text = "".join(char if char.isalnum() or char in "._-" else "-" for char in str(value or ""))
    return text.strip(".-")[:48] or "artifact"


def _write_bytes_atomic(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile_mkstemp_same_dir(parent, os.path.basename(path))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def quarantine_dir(base_dir: str) -> str:
    path = os.path.join(base_dir, QUARANTINE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def quarantine_file(
    base_dir: str,
    source_path: str,
    *,
    category: str,
    reason: str,
    detail: str = "",
) -> dict:
    """Copy a damaged file into quarantine, leaving the source untouched.

    The source is copied, never moved: another process may still hold a valid
    handle, and moving a profile file out from under it would turn a read
    problem into a data-loss event.  The returned record is safe to show in a
    diagnostics report — it contains a relative path and a checksum, not the
    file contents.
    """
    if not _inside(base_dir, source_path):
        raise StorageHealthError("Refusing to quarantine a file outside this profile")
    if not os.path.isfile(source_path):
        raise StorageHealthError("The file to quarantine no longer exists")
    try:
        size = os.path.getsize(source_path)
    except OSError as exc:
        raise StorageHealthError(f"Could not stat the damaged file: {exc}") from exc
    if size > MAX_QUARANTINE_BYTES:
        raise StorageHealthError("The damaged file is too large to copy safely")
    try:
        with open(source_path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise StorageHealthError(f"Could not read the damaged file: {exc}") from exc

    digest = _sha256_bytes(data)
    original = os.path.relpath(source_path, base_dir)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    stem = _safe_fragment(os.path.splitext(os.path.basename(source_path))[0])
    extension = os.path.splitext(source_path)[1] or ".bin"
    directory = quarantine_dir(base_dir)
    artifact = os.path.join(directory, f"{stamp}-{stem}-{digest[:12]}{extension}")
    if os.path.exists(artifact):
        artifact = os.path.join(
            directory, f"{stamp}-{stem}-{digest[:12]}-{uuid.uuid4().hex[:8]}{extension}"
        )
    metadata_path = artifact + ".json"
    if os.path.exists(metadata_path):
        metadata_path = f"{artifact}.{uuid.uuid4().hex[:8]}.json"

    _write_bytes_atomic(artifact, data)
    metadata = {
        "kind": "mei.quarantine",
        "version": 1,
        "created_at": int(time.time()),
        "original_path": original.replace("\\", "/"),
        "category": str(category or "store"),
        "reason": str(reason or "unknown")[:500],
        "detail": str(detail or "")[:1000],
        "size": len(data),
        "sha256": digest,
        "artifact": os.path.basename(artifact),
        "source_preserved": True,
    }
    try:
        from litebrowser.core.storage_utils import write_json

        write_json(metadata_path, metadata)
        try:
            os.chmod(artifact, 0o600)
            os.chmod(metadata_path, 0o600)
        except OSError:
            pass
    except Exception:
        # The copy is the safety property; a missing sidecar must not delete it.
        _log.warning("quarantine copy written but metadata failed: %s", metadata_path)
    _log.warning("quarantined %s (%s): %s", original, reason, detail)
    return metadata


def list_quarantine(base_dir: str) -> list[dict]:
    """Metadata for quarantined artifacts, newest first, without their bytes."""
    directory = os.path.join(base_dir, QUARANTINE_DIR)
    if not os.path.isdir(directory):
        return []
    records = []
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        result = read_json_checked(path, dict)
        if result.ok and result.value.get("kind") == "mei.quarantine":
            records.append(dict(result.value))
    records.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return records


def store_health(base_dir: str) -> list[dict]:
    """Return one explicit read outcome for every catalogued user store.

    Missing optional stores are available and intentionally not findings.  A
    zero-byte, malformed, wrong-root, oversized or unreadable file is *not*
    available, even though legacy callers still receive their default value.
    The UI can use this inventory to say "tasks are unavailable" instead of
    drawing an empty task list as if the user had no tasks.
    """
    quarantined = {
        os.path.normcase(str(row.get("original_path") or "").replace("/", os.sep)): row
        for row in list_quarantine(base_dir)
    }
    rows = []
    for descriptor in STORES:
        path = os.path.join(base_dir, descriptor.name)
        expected = dict if descriptor.root == "dict" else list
        result = read_json_checked(path, expected)
        relative = descriptor.name.replace("\\", "/")
        artifact = quarantined.get(os.path.normcase(descriptor.name.replace("/", os.sep)))
        available = result.ok or (result.status == STATUS_MISSING and descriptor.optional)
        rows.append(
            {
                "name": relative,
                "category": descriptor.category,
                "restore_group": descriptor.restore_group,
                "status": result.status,
                "available": bool(available),
                "corrupt": bool(result.corrupt),
                "size": int(result.size),
                "sha256": result.sha256,
                "detail": result.detail,
                "recovery_artifact": dict(artifact) if artifact else {},
            }
        )
    return rows


def unavailable_stores(base_dir: str) -> list[dict]:
    """Stores whose current bytes cannot be interpreted safely."""
    return [row for row in store_health(base_dir) if not row["available"]]


def health_summary(base_dir: str) -> dict:
    rows = store_health(base_dir)
    unavailable = [row for row in rows if not row["available"]]
    return {
        "stores": rows,
        "total": len(rows),
        "available": sum(1 for row in rows if row["available"]),
        "unavailable": unavailable,
        "unavailable_count": len(unavailable),
        "healthy": not unavailable,
        "quarantine_count": len(list_quarantine(base_dir)),
    }


__all__ = [
    "MAX_JSON_BYTES",
    "QUARANTINE_DIR",
    "RECOVERY_DIR",
    "JsonReadResult",
    "StorageHealthError",
    "file_sha256",
    "health_summary",
    "list_quarantine",
    "quarantine_dir",
    "quarantine_file",
    "read_json_checked",
    "store_health",
    "unavailable_stores",
]
