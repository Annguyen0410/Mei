import json
import os
import secrets
from typing import Any

_JSON_ENCODER = json.JSONEncoder(ensure_ascii=False, indent=2, sort_keys=False)


def read_json(path: str, default: Any):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def _atomic_replace(tmp_path: str, final_path: str) -> None:
    os.replace(tmp_path, final_path)


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


def write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    base_name = os.path.basename(path) or "data.json"
    fd, tmp_path = tempfile_mkstemp_same_dir(parent or os.getcwd(), base_name)
    try:
        serialized = _JSON_ENCODER.encode(data)
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
