"""Page monitor: watch a URL for changes and toast when it shifts.

monitors.json (per profile): {"version":1,"monitors":[
  {"id":"...","url":"...","title":"...","hash":"...","last_checked":unix,"enabled":true}
]}

Checks run on the shell's executor every 15 minutes: fetch the URL with
urllib (raw HTML — pages that need JS are a known limitation), hash it, and
compare with the stored hash. First check seeds the hash without alerting.
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.request

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, "monitors.json")


def load_monitors(base_dir: str) -> list[dict]:
    data = read_json(_path(base_dir), {"version": 1, "monitors": []})
    monitors = data.get("monitors") if isinstance(data, dict) else None
    return [m for m in monitors if isinstance(m, dict)] if isinstance(monitors, list) else []


def save_monitors(base_dir: str, monitors: list[dict]) -> None:
    with profile_locked(base_dir):
        write_json(_path(base_dir), {"version": 1, "monitors": monitors})


def add_monitor(base_dir: str, url: str, title: str = "") -> dict:
    monitors = load_monitors(base_dir)
    if any(m.get("url") == url for m in monitors):
        return {}
    monitor = {
        "id": os.urandom(6).hex(),
        "url": url,
        "title": (title or url)[:80],
        "hash": "",
        "last_checked": 0,
        "enabled": True,
    }
    monitors.append(monitor)
    save_monitors(base_dir, monitors)
    return monitor


def remove_monitor(base_dir: str, monitor_id: str) -> bool:
    monitors = load_monitors(base_dir)
    kept = [m for m in monitors if m.get("id") != monitor_id]
    if len(kept) == len(monitors):
        return False
    save_monitors(base_dir, kept)
    return True


def fetch_and_hash(url: str, timeout: float = 15.0) -> str | None:
    """Raw HTML hash through the system proxy path; None on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mei/6 page-monitor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2 * 1024 * 1024)
    except Exception:
        return None
    return hashlib.blake2s(body, digest_size=16).hexdigest()


def due_monitors(base_dir: str, interval_seconds: int = 15 * 60) -> list[dict]:
    now = int(time.time())
    return [m for m in load_monitors(base_dir) if m.get("enabled") and now - int(m.get("last_checked", 0) or 0) >= interval_seconds]


def record_check(base_dir: str, monitor_id: str, content_hash: str) -> str:
    """Store the new hash; returns 'changed' | 'same' | 'seeded'."""
    monitors = load_monitors(base_dir)
    outcome = "same"
    for m in monitors:
        if m.get("id") != monitor_id:
            continue
        old = str(m.get("hash") or "")
        if not old:
            outcome = "seeded"
        elif old != content_hash:
            outcome = "changed"
        m["hash"] = content_hash
        m["last_checked"] = int(time.time())
        break
    save_monitors(base_dir, monitors)
    return outcome
