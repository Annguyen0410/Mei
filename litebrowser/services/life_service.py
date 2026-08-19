import os
import time
import uuid
from datetime import datetime, timezone

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json
from litebrowser.services import history_service


def _entity_path(base_dir: str, name: str) -> str:
    return os.path.join(base_dir, name)


def _now() -> int:
    return int(time.time())


def _due_at_to_unix(due_at) -> int:
    if due_at is None:
        return 0
    if isinstance(due_at, bool):
        return 0
    if isinstance(due_at, int):
        return int(due_at)
    if isinstance(due_at, float):
        return int(due_at)
    s = str(due_at).strip()
    if not s:
        return 0
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _read_list(path: str):
    data = read_json(path, [])
    return data if isinstance(data, list) else []


def _write_list(path: str, items):
    write_json(path, items if isinstance(items, list) else [])


def tasks_path(base_dir: str) -> str:
    return _entity_path(base_dir, "tasks.json")


def calendar_path(base_dir: str) -> str:
    return _entity_path(base_dir, "calendar.json")


def boards_path(base_dir: str) -> str:
    return _entity_path(base_dir, "boards.json")


def saved_pages_path(base_dir: str) -> str:
    return _entity_path(base_dir, "saved_pages.json")


def sync_state_path(base_dir: str) -> str:
    return _entity_path(base_dir, "sync_state.json")


def sync_account_path(base_dir: str) -> str:
    return _entity_path(base_dir, "sync_account.json")


def load_tasks(base_dir: str):
    with profile_locked(base_dir):
        return _read_list(tasks_path(base_dir))


def save_tasks(base_dir: str, items):
    with profile_locked(base_dir):
        _write_list(tasks_path(base_dir), items)


def add_task(base_dir: str, title: str, bucket: str = "personal", due_at: int | str = 0, notes: str | None = None):
    with profile_locked(base_dir):
        items = load_tasks(base_dir)
        now = _now()
        due_unix = _due_at_to_unix(due_at)
        item = {
            "id": uuid.uuid4().hex,
            "title": (title or "").strip(),
            "bucket": bucket or "personal",
            "completed": False,
            "due_at": due_unix,
            "workspace_id": "default",
            "created_at": now,
            "updated_at": now,
            "sync_state": "local",
            "archived": False,
        }
        if notes is not None and str(notes).strip():
            item["notes"] = str(notes).strip()
        items.append(item)
        _write_list(tasks_path(base_dir), items)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "task", item["title"], f"Task added in {item['bucket']}", {"task_id": item["id"]})
        return item


def toggle_task(base_dir: str, task_id: str):
    with profile_locked(base_dir):
        items = load_tasks(base_dir)
        for item in items:
            if item.get("id") == task_id:
                item["completed"] = not bool(item.get("completed"))
                item["updated_at"] = _now()
                _write_list(tasks_path(base_dir), items)
                _touch_sync_state(base_dir)
                state = "completed" if item["completed"] else "reopened"
                history_service.log_event(base_dir, "task", item.get("title", ""), f"Task {state}", {"task_id": item.get("id", "")})
                return item
        return None


def remove_task(base_dir: str, task_id: str) -> bool:
    with profile_locked(base_dir):
        items = load_tasks(base_dir)
        after = [item for item in items if item.get("id") != task_id]
        if len(after) == len(items):
            return False
        _write_list(tasks_path(base_dir), after)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "task", task_id, "Task deleted", {"task_id": task_id})
        return True


def load_events(base_dir: str):
    with profile_locked(base_dir):
        return _read_list(calendar_path(base_dir))


def save_events(base_dir: str, items):
    with profile_locked(base_dir):
        _write_list(calendar_path(base_dir), items)


def add_event(base_dir: str, title: str, starts_at: int, bucket: str = "life"):
    with profile_locked(base_dir):
        items = load_events(base_dir)
        now = _now()
        item = {
            "id": uuid.uuid4().hex,
            "title": (title or "").strip(),
            "starts_at": int(starts_at or 0),
            "bucket": bucket or "life",
            "workspace_id": "default",
            "created_at": now,
            "updated_at": now,
            "sync_state": "local",
            "archived": False,
        }
        items.append(item)
        items.sort(key=lambda x: int(x.get("starts_at", 0) or 0))
        _write_list(calendar_path(base_dir), items)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "calendar", item["title"], "Calendar event added", {"event_id": item["id"], "starts_at": item["starts_at"]})
        return item


def remove_event(base_dir: str, event_id: str) -> bool:
    with profile_locked(base_dir):
        items = load_events(base_dir)
        after = [item for item in items if item.get("id") != event_id]
        if len(after) == len(items):
            return False
        _write_list(calendar_path(base_dir), after)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "calendar", event_id, "Calendar event deleted", {"event_id": event_id})
        return True


def load_boards(base_dir: str):
    with profile_locked(base_dir):
        items = _read_list(boards_path(base_dir))
        normalized = []
        changed = False
        for board in items:
            current = _normalize_board(board)
            if current is None:
                changed = True
                continue
            if current != board:
                changed = True
            normalized.append(current)
        if changed:
            _write_list(boards_path(base_dir), normalized)
        return normalized


def save_boards(base_dir: str, items):
    with profile_locked(base_dir):
        _write_list(boards_path(base_dir), items)


def add_board(base_dir: str, title: str):
    with profile_locked(base_dir):
        items = _read_list(boards_path(base_dir))
        now = _now()
        board = {
            "id": uuid.uuid4().hex,
            "title": (title or "").strip() or "Untitled board",
            "nodes": [],
            "edges": [],
            "strokes": [],
            "workspace_id": "default",
            "created_at": now,
            "updated_at": now,
            "sync_state": "local",
            "archived": False,
        }
        items.append(board)
        _write_list(boards_path(base_dir), items)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "board", board["title"], "Board created", {"board_id": board["id"]})
        return board


def update_board(base_dir: str, board):
    with profile_locked(base_dir):
        items = _read_list(boards_path(base_dir))
        for index, item in enumerate(items):
            if item.get("id") == board.get("id"):
                board = _normalize_board(board) or item
                board["updated_at"] = _now()
                items[index] = board
                _write_list(boards_path(base_dir), items)
                _touch_sync_state(base_dir)
                history_service.log_event(base_dir, "board", board.get("title", ""), "Board updated", {"board_id": board.get("id", "")})
                return board
        return None


def remove_board(base_dir: str, board_id: str) -> bool:
    with profile_locked(base_dir):
        items = _read_list(boards_path(base_dir))
        after = [item for item in items if item.get("id") != board_id]
        if len(after) == len(items):
            return False
        _write_list(boards_path(base_dir), after)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "board", board_id, "Board deleted", {"board_id": board_id})
        return True


def add_board_node(base_dir: str, board_id: str, title: str, kind: str = "sticky", payload: str = "", x: float = 40, y: float = 40):
    with profile_locked(base_dir):
        items = _read_list(boards_path(base_dir))
        for board in items:
            if board.get("id") == board_id:
                node = {
                    "id": uuid.uuid4().hex,
                    "kind": kind,
                    "title": title or "Card",
                    "x": float(x),
                    "y": float(y),
                    "color": "#c39d63",
                    "payload": payload or "",
                }
                board.setdefault("nodes", []).append(node)
                board["updated_at"] = _now()
                _write_list(boards_path(base_dir), items)
                _touch_sync_state(base_dir)
                history_service.log_event(base_dir, "board-note", node["title"], "Board card added", {"board_id": board_id, "node_id": node["id"]})
                return node
        return None


def _normalize_board(board):
    if not isinstance(board, dict):
        return None
    normalized = dict(board)
    normalized["id"] = normalized.get("id") or uuid.uuid4().hex
    normalized["title"] = (normalized.get("title") or "").strip() or "Untitled board"
    normalized["nodes"] = normalized.get("nodes") if isinstance(normalized.get("nodes"), list) else []
    normalized["edges"] = normalized.get("edges") if isinstance(normalized.get("edges"), list) else []
    normalized["strokes"] = normalized.get("strokes") if isinstance(normalized.get("strokes"), list) else []
    normalized.setdefault("workspace_id", "default")
    normalized.setdefault("created_at", _now())
    normalized.setdefault("updated_at", normalized.get("created_at") or _now())
    normalized.setdefault("sync_state", "local")
    normalized.setdefault("archived", False)
    return normalized


def load_saved_pages(base_dir: str):
    with profile_locked(base_dir):
        return _read_list(saved_pages_path(base_dir))


def save_saved_pages(base_dir: str, items):
    with profile_locked(base_dir):
        _write_list(saved_pages_path(base_dir), items)


def add_saved_page(base_dir: str, title: str, url: str, summary: str = ""):
    with profile_locked(base_dir):
        items = _read_list(saved_pages_path(base_dir))
        now = _now()
        existing = None
        for item in items:
            if item.get("url") == url:
                existing = item
                break
        if existing:
            existing["title"] = title or existing.get("title") or url
            existing["summary"] = summary or existing.get("summary") or ""
            existing["updated_at"] = now
            _write_list(saved_pages_path(base_dir), items)
            _touch_sync_state(base_dir)
            history_service.log_event(base_dir, "saved-page", existing.get("title", "") or url, "Saved page updated", {"saved_page_id": existing.get("id", ""), "url": url})
            return existing
        item = {
            "id": uuid.uuid4().hex,
            "title": title or url,
            "url": url,
            "summary": summary or "",
            "workspace_id": "default",
            "created_at": now,
            "updated_at": now,
            "sync_state": "local",
            "archived": False,
        }
        items.append(item)
        _write_list(saved_pages_path(base_dir), items)
        _touch_sync_state(base_dir)
        history_service.log_event(base_dir, "saved-page", item["title"], "Page saved to library", {"saved_page_id": item["id"], "url": item["url"]})
        return item


def load_sync_state(base_dir: str):
    with profile_locked(base_dir):
        data = read_json(sync_state_path(base_dir), None)
    if not isinstance(data, dict):
        return {"enabled": False, "last_sync_at": 0, "pending_changes": 0, "mode": "local-cache"}
    data.setdefault("enabled", False)
    data.setdefault("last_sync_at", 0)
    data.setdefault("pending_changes", 0)
    data.setdefault("mode", "local-cache")
    return data


def save_sync_state(base_dir: str, data):
    with profile_locked(base_dir):
        write_json(sync_state_path(base_dir), data)


def load_sync_account(base_dir: str):
    with profile_locked(base_dir):
        data = read_json(sync_account_path(base_dir), None)
    return data if isinstance(data, dict) else {"id": "", "email": "", "display_name": "", "status": "offline-ready"}


def save_sync_account(base_dir: str, email: str, display_name: str, enabled: bool = True):
    with profile_locked(base_dir):
        account = {
            "id": uuid.uuid4().hex,
            "email": (email or "").strip(),
            "display_name": (display_name or "").strip() or "Mei user",
            "status": "connected" if enabled else "offline-ready",
        }
        write_json(sync_account_path(base_dir), account)
        state = load_sync_state(base_dir)
        state["enabled"] = bool(enabled)
        state["last_sync_at"] = _now()
        state["mode"] = "local-cache"
        write_json(sync_state_path(base_dir), state)
        history_service.log_event(base_dir, "account", account.get("display_name", "") or account.get("email", ""), "Sync account updated", {"email": account.get("email", ""), "enabled": enabled})
        return account


def _touch_sync_state(base_dir: str):
    state = load_sync_state(base_dir)
    state["pending_changes"] = int(state.get("pending_changes", 0) or 0) + 1
    write_json(sync_state_path(base_dir), state)


def get_dashboard_snapshot(base_dir: str):
    tasks = load_tasks(base_dir)
    events = load_events(base_dir)
    boards = load_boards(base_dir)
    saved_pages = load_saved_pages(base_dir)
    pending = len([item for item in tasks if not item.get("completed")])
    upcoming = sorted([item for item in events if int(item.get("starts_at", 0) or 0) >= _now()], key=lambda x: int(x.get("starts_at", 0) or 0))[:5]
    return {
        "tasks_total": len(tasks),
        "tasks_pending": pending,
        "events_upcoming": upcoming,
        "boards_total": len(boards),
        "saved_pages_total": len(saved_pages),
    }


def search_everything(base_dir: str, query: str):
    q = (query or "").strip().lower()
    if not q:
        return []
    results = []
    for task in load_tasks(base_dir):
        if q in (task.get("title") or "").lower():
            results.append({"kind": "task", "title": task.get("title", ""), "id": task.get("id", ""), "subtitle": task.get("bucket", "")})
    for event in load_events(base_dir):
        if q in (event.get("title") or "").lower():
            results.append({"kind": "event", "title": event.get("title", ""), "id": event.get("id", ""), "subtitle": "calendar"})
    for board in load_boards(base_dir):
        if q in (board.get("title") or "").lower():
            results.append({"kind": "board", "title": board.get("title", ""), "id": board.get("id", ""), "subtitle": "board"})
        for node in board.get("nodes", []):
            if q in (node.get("title") or "").lower() or q in (node.get("payload") or "").lower():
                results.append({"kind": "board-node", "title": node.get("title", ""), "id": board.get("id", ""), "subtitle": board.get("title", "")})
    for page in load_saved_pages(base_dir):
        if q in (page.get("title") or "").lower() or q in (page.get("url") or "").lower():
            results.append({"kind": "saved-page", "title": page.get("title", ""), "id": page.get("id", ""), "subtitle": page.get("url", "")})
    return results[:50]
