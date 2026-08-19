"""Re-entrant lock per profile directory (same process: UI + bridge threads)."""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_registry_lock = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def _profile_key(base_dir: str) -> str:
    return os.path.normcase(os.path.abspath(base_dir))


@contextmanager
def profile_locked(base_dir: str) -> Iterator[None]:
    key = _profile_key(base_dir)
    with _registry_lock:
        rlock = _locks.get(key)
        if rlock is None:
            rlock = threading.RLock()
            _locks[key] = rlock
    rlock.acquire()
    try:
        yield
    finally:
        rlock.release()
