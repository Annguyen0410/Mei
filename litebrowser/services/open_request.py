"""Cross-thread \"open this URL in the browser\" request queue.

The Android bridge (mobile bridge HTTP server) runs on its own thread and can
NOT touch the Qt GUI directly. Instead it appends requests here; the main
window drains them on a QTimer and opens the URLs in real tabs.

File lives in the profile dir so multiple windows/profiles never mix.
"""

import os
import threading
from typing import Any

from litebrowser.core import storage_utils

_lock = threading.Lock()
_FILE_NAME = "pending_open_tabs.json"
_MAX_STORED = 200


def requests_path(base_dir: str) -> str:
    return os.path.join(base_dir, _FILE_NAME)


def push_open_request(base_dir: str, request: dict[str, Any]) -> None:
    """Append one request {source, url, label, kind} (thread-safe)."""
    if not isinstance(request, dict) or not str(request.get("url") or "").strip():
        return
    url = str(request["url"]).strip()
    if not url.startswith(("http://", "https://", "file://")):
        return
    with _lock:
        data = storage_utils.read_json(requests_path(base_dir), {"version": 1, "requests": []})
        requests = data.get("requests") if isinstance(data, dict) else []
        if not isinstance(requests, list):
            requests = []
        requests.append(
            {
                "source": str(request.get("source") or "unknown"),
                "url": url,
                "label": str(request.get("label") or "").strip() or url,
                "kind": str(request.get("kind") or "url"),
                "at": _now_iso(),
            }
        )
        requests = requests[-_MAX_STORED:]
        storage_utils.write_json(requests_path(base_dir), {"version": 1, "requests": requests})


def drain_open_requests(base_dir: str) -> list[dict[str, Any]]:
    """Return all pending requests and clear the queue (thread-safe)."""
    with _lock:
        path = requests_path(base_dir)
        # Fast path: nothing pending → skip both the read AND the write. The
        # GUI polls this every 2.5 s; v6.4 rewrote the file even when empty,
        # costing a disk write every tick for the app's whole lifetime.
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return []
        if not raw.strip():
            return []
        data = storage_utils.read_json(path, {"version": 1, "requests": []})
        requests = data.get("requests") if isinstance(data, dict) else []
        if not isinstance(requests, list):
            requests = []
        if requests:
            storage_utils.write_json(path, {"version": 1, "requests": []})
    return requests


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")