"""Self-hosted sync — push/pull a profile snapshot to your own HTTP endpoint.

The endpoint is a tiny API you run yourself (see README "Self-hosted sync"):
POST /api/sync/push stores the latest snapshot, GET /api/sync/latest returns
it. Every request carries a Bearer token. The payload is one JSON bundle
containing the local data (tasks, events, boards, saved pages, notes,
bookmarks, history) so two machines can stay in step without any cloud.
"""

from __future__ import annotations

import json
import time
import urllib.request

from litebrowser.core import prefs
from litebrowser.services import life_service, personal_service

SYNC_API_VERSION = 1


def _bundle(base_dir: str) -> dict:
    notes = personal_service.list_notes(base_dir) or []
    return {
        "app": "litebrowser",
        "kind": "snapshot",
        "api": SYNC_API_VERSION,
        "exported_at": int(time.time()),
        "tasks": life_service.load_tasks(base_dir) or [],
        "events": life_service.load_events(base_dir) or [],
        "boards": life_service.load_boards(base_dir) or [],
        "saved_pages": life_service.load_saved_pages(base_dir) or [],
        "notes": [
            {
                "title": n.get("title", ""),
                "category": n.get("category", "General"),
                "content": n.get("content", ""),
            }
            for n in notes
        ],
        "bookmarks": prefs.load_bookmarks(base_dir) or [],
        "history": [list(item) for item in (prefs.load_history_entries(base_dir) or [])[:500]],
    }


def _upsert(existing, incoming, key="id"):
    seen = {item.get(key) for item in incoming if item.get(key)}
    merged = [item for item in existing if item.get(key) not in seen]
    merged.extend(incoming)
    return merged


def _apply_bundle(base_dir: str, bundle: dict) -> dict:
    """Merge a remote snapshot into the local profile (last-writer-wins per item)."""
    applied = {"tasks": 0, "events": 0, "boards": 0, "pages": 0, "notes": 0, "bookmarks": 0, "history": 0}

    tasks = _upsert(life_service.load_tasks(base_dir), bundle.get("tasks") or [])
    life_service.save_tasks(base_dir, tasks)
    applied["tasks"] = len(bundle.get("tasks") or [])

    events = _upsert(life_service.load_events(base_dir), bundle.get("events") or [])
    life_service.save_events(base_dir, events)
    applied["events"] = len(bundle.get("events") or [])

    boards = _upsert(life_service.load_boards(base_dir), bundle.get("boards") or [])
    life_service.save_boards(base_dir, boards)
    applied["boards"] = len(bundle.get("boards") or [])

    pages = _upsert(life_service.load_saved_pages(base_dir), bundle.get("saved_pages") or [])
    life_service.save_saved_pages(base_dir, pages)
    applied["pages"] = len(bundle.get("saved_pages") or [])

    for note in bundle.get("notes") or []:
        title = (note.get("title") or "").strip()
        category = (note.get("category") or "General").strip() or "General"
        content = note.get("content") or ""
        if not title:
            continue
        existing = [
            n for n in personal_service.list_notes(base_dir)
            if n.get("title", "").strip() == title and (n.get("category") or "General").strip() == category
        ]
        if existing:
            personal_service.update_note(base_dir, existing[0]["id"], content, category)
        else:
            personal_service.create_note(base_dir, title, content, category)
        applied["notes"] += 1

    remote_bookmarks = bundle.get("bookmarks") or []
    if remote_bookmarks:
        # Merge by URL instead of wholesale replace: v6.4 overwrote local
        # bookmarks with the remote set, so pulling from a device with sparse
        # data silently deleted everything saved on this machine.
        local_bookmarks = prefs.load_bookmarks(base_dir) or []
        local_by_url = {}
        for bm in local_bookmarks:
            if isinstance(bm, dict) and bm.get("url"):
                local_by_url[bm["url"]] = bm
        merged = list(local_bookmarks)
        for bm in remote_bookmarks:
            if not isinstance(bm, dict) or not bm.get("url"):
                continue
            if bm["url"] in local_by_url:
                continue
            merged.append(bm)
            local_by_url[bm["url"]] = bm
        if merged != local_bookmarks:
            prefs.save_bookmarks(base_dir, merged)
        applied["bookmarks"] = len(remote_bookmarks)

    remote_history = [tuple(item) for item in (bundle.get("history") or [])]
    if remote_history:
        existing = prefs.load_history_entries(base_dir)
        merged = existing + [item for item in remote_history if item not in existing]
        merged.sort(key=lambda item: -int(item[0] or 0))
        # Keep a generous cap: v6.4 trimmed to 1500, so one pull from a
        # sparse device could throw away months of local history.
        prefs.save_history_entries(base_dir, merged[:5000])
        applied["history"] = len(remote_history)
    return applied


def _request(url: str, token: str, method: str = "GET", payload=None) -> tuple[bool, object, str]:
    try:
        headers = {
            "Authorization": "Bearer %s" % token,
            "X-Mei-Sync": "1",
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            parsed = None
            if body.strip():
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = body
            return True, parsed, ""
    except Exception as exc:
        return False, None, str(exc)


def push(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    endpoint = (endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False, "No sync endpoint set."
    ok, _resp, err = _request(endpoint + "/api/sync/push", token, method="POST", payload=_bundle(base_dir))
    if not ok:
        return False, "Push failed: %s" % (err or "connection error")
    _record_sync(base_dir, pushed_at=int(time.time()))
    return True, "Pushed snapshot."


def pull(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    endpoint = (endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False, "No sync endpoint set."
    ok, resp, err = _request(endpoint + "/api/sync/latest", token)
    if not ok:
        return False, "Pull failed: %s" % (err or "connection error")
    if not isinstance(resp, dict) or resp.get("kind") != "snapshot":
        return False, "Remote did not return a snapshot."
    applied = _apply_bundle(base_dir, resp)
    _record_sync(base_dir, pulled_at=int(time.time()))
    counts = " · ".join("%s=%s" % (k, v) for k, v in applied.items() if v)
    return True, "Pulled snapshot. (%s)" % (counts or "no changes")


def sync_now(base_dir: str, endpoint: str, token: str) -> tuple[bool, str]:
    ok_push, msg_push = push(base_dir, endpoint, token)
    ok_pull, msg_pull = pull(base_dir, endpoint, token)
    if ok_push and ok_pull:
        return True, msg_push + " " + msg_pull
    return False, (msg_push if not ok_push else msg_pull)


def _record_sync(base_dir: str, pushed_at: int | None = None, pulled_at: int | None = None):
    data = life_service.load_sync_state(base_dir)
    if pushed_at:
        data["last_push_at"] = pushed_at
    if pulled_at:
        data["last_pull_at"] = pulled_at
    data["last_sync_at"] = int(time.time())
    life_service.save_sync_state(base_dir, data)


def last_sync(base_dir: str) -> int | None:
    data = life_service.load_sync_state(base_dir)
    value = int(data.get("last_sync_at") or 0)
    return value or None
