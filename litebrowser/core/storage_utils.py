import json
import os
import secrets
import threading
import time
from typing import Any

from litebrowser.core.log import get_logger

_log = get_logger("storage_utils")
_JSON_ENCODER = json.JSONEncoder(ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False)
_WRITE_LOCK = threading.RLock()

#: Paths whose current bytes are known to be malformed.  A read still returns the
#: caller's default so one damaged optional store cannot crash the shell, but a
#: later write is refused: silently replacing the only copy would turn a
#: recoverable parse error into permanent data loss.  A successful read clears
#: the mark (the user or a recovery tool repaired the file).
_DAMAGED_PATHS: dict[str, str] = {}


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _preserve_corrupt_copy(path: str) -> str:
    """Keep a private adjacent copy before the store can ever be overwritten."""
    parent = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    base = os.path.basename(path) or "store"
    name = f".{base}.corrupt-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}.bak"
    target = os.path.join(parent, name)
    fd, temporary = tempfile_mkstemp_same_dir(parent, base)
    try:
        with os.fdopen(fd, "wb") as target_handle, open(path, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                target_handle.write(block)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        _atomic_replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def damaged_paths() -> dict[str, str]:
    """Read-only view of stores whose bytes are preserved but not overwritable."""
    return dict(_DAMAGED_PATHS)


def safe_child_path(root: str, relative: str) -> str:
    """Resolve an untrusted child path without traversal or symlink escapes.

    Apply Windows restrictions on every platform so exchanged backups and
    bridge messages have the same interpretation on each device.
    """
    if not isinstance(relative, str) or not relative or "\x00" in relative or ":" in relative:
        return ""
    normalized = relative.replace("\\", "/")
    if normalized.startswith("/") or any(part in ("", ".", "..") for part in normalized.split("/")):
        return ""
    root_path = os.path.normcase(os.path.realpath(root))
    path = os.path.realpath(os.path.join(root_path, *normalized.split("/")))
    try:
        if os.path.commonpath([root_path, os.path.normcase(path)]) != root_path or os.path.normcase(path) == root_path:
            return ""
    except ValueError:
        return ""
    return path


def read_json(path: str, default: Any):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                value = json.load(f)
            _DAMAGED_PATHS.pop(_path_key(path), None)
            return value
        except (OSError, ValueError, UnicodeError) as exc:
            artifact = ""
            try:
                artifact = _preserve_corrupt_copy(path)
            except OSError as copy_exc:
                _log.warning("could not preserve damaged store %s: %s", path, copy_exc)
            key = _path_key(path)
            if key not in _DAMAGED_PATHS:
                _DAMAGED_PATHS[key] = artifact
            _log.warning(
                "read_json failed for %s: %s; preserved at %s",
                path,
                exc,
                artifact or "(copy unavailable)",
            )
    else:
        _DAMAGED_PATHS.pop(_path_key(path), None)
    return default


def _existing_json_is_damaged(path: str) -> bool:
    """Return True when a file that is about to be replaced is not valid JSON.

    This check is deliberately done at write time as well as read time.  The
    in-memory damage map only protects a process that has already read the
    store; a background worker can otherwise be the first writer after a
    restart and erase bytes that were never read in this session.
    """
    if not os.path.isfile(path):
        return False
    try:
        size = os.path.getsize(path)
        if size == 0:
            return True
        with open(path, "rb") as handle:
            data = handle.read()
        json.loads(data.decode("utf-8-sig"))
        return False
    except (OSError, ValueError, UnicodeError):
        return True


def _atomic_replace(tmp_path: str, final_path: str) -> None:
    """Replace a file atomically, tolerating short-lived Windows file locks.

    Antivirus scanners and Explorer previews can briefly hold a profile file
    open just as an atomic write is committed.  Retrying the final rename keeps
    the existing file intact while avoiding an unnecessary failed save.
    """
    for attempt in range(5):
        try:
            os.replace(tmp_path, final_path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.01 * (attempt + 1))


def write_text_atomic(path: str, text: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    base_name = os.path.basename(path) or "file"
    fd, tmp_path = tempfile_mkstemp_same_dir(parent, base_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text or "")
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def tempfile_mkstemp_same_dir(parent: str, base_hint: str) -> tuple[int, str]:
    for _ in range(16):
        suffix = secrets.token_hex(4)
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base_hint)[:40] or "tmp"
        name = f".{safe}.{suffix}.tmp"
        candidate = os.path.join(parent, name)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            return fd, candidate
        except FileExistsError:
            continue
    raise OSError("Could not create unique temp file")


def write_json(path: str, data: Any, *, allow_replace_corrupt: bool = False) -> None:
    # The write-time damage check must not race another Mei writer inspecting
    # the same path.  A process-wide re-entrant lock is cheap and keeps the
    # previous atomic-replace guarantees intact; the profile lock remains the
    # cross-process boundary.
    with _WRITE_LOCK:
        return _write_json_unlocked(
            path, data, allow_replace_corrupt=allow_replace_corrupt
        )


def _write_json_unlocked(
    path: str, data: Any, *, allow_replace_corrupt: bool = False
) -> None:
    # A store that failed to parse is preserved and write-protected until a
    # successful read confirms it was repaired.  Do not turn a parse error into
    # permanent loss by writing a default payload over the only copy.
    artifact = _DAMAGED_PATHS.get(_path_key(path))
    if not artifact and not allow_replace_corrupt and _existing_json_is_damaged(path):
        try:
            artifact = _preserve_corrupt_copy(path)
        except OSError as exc:
            artifact = ""
            _log.warning("could not preserve damaged store %s: %s", path, exc)
        key = _path_key(path)
        if key not in _DAMAGED_PATHS:
            _DAMAGED_PATHS[key] = artifact
    if artifact:
        raise OSError(
            "Refusing to overwrite a damaged store; its bytes were preserved at "
            + artifact
            + ". Restore it from backup or repair it explicitly."
        )
    if allow_replace_corrupt:
        _DAMAGED_PATHS.pop(_path_key(path), None)
    # Encode before allocating a file descriptor: invalid payloads must not
    # leak handles or touch the previous on-disk value.
    serialized = _JSON_ENCODER.encode(data)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    base_name = os.path.basename(path) or "data.json"
    fd, tmp_path = tempfile_mkstemp_same_dir(parent or os.getcwd(), base_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
