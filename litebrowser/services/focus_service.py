"""Café Focus — a pomodoro-style focus timer persisted per profile.

The barista analogy: you "order a pour" (start a session) for N minutes, the
timer counts down, and completed sessions land in the focus journal so the
Personal Hub can show today's focus time.
"""
import os
import time
import uuid
from datetime import datetime

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json

SESSION_FILE = "focus_sessions.json"


def sessions_path(base_dir: str) -> str:
    return os.path.join(base_dir, SESSION_FILE)


def _now() -> int:
    return int(time.time())


def _load(base_dir: str) -> dict:
    data = read_json(sessions_path(base_dir), {})
    return data if isinstance(data, dict) else {}


def _save(base_dir: str, data: dict) -> None:
    with profile_locked(base_dir):
        write_json(sessions_path(base_dir), data)


def start_focus(base_dir: str, minutes: int = 25, label: str = "") -> dict:
    """Start (or restart) a focus session. Returns the active session record.

    Only one session runs at a time; starting a new one discards an unfinished
    previous pour and records it as abandoned so history stays honest.
    """
    minutes = max(1, min(int(minutes or 25), 180))
    data = _load(base_dir)
    now = _now()
    active = data.get("active")
    if active:
        _close_active(data, "abandoned")
    session = {
        "id": uuid.uuid4().hex[:12],
        "label": (label or "").strip() or f"{minutes} min focus",
        "minutes": minutes,
        "started_at": now,
        "ends_at": now + minutes * 60,
        "status": "running",
    }
    data["active"] = session
    data.setdefault("sessions", [])
    _save(base_dir, data)
    return session


def focus_status(base_dir: str) -> dict:
    """Current running session (or None) with remaining seconds computed live."""
    data = _load(base_dir)
    active = data.get("active")
    if not active:
        return {"running": False, "session": None, "remaining": 0}
    remaining = max(0, int(active.get("ends_at", 0)) - _now())
    if remaining <= 0:
        return _finish(base_dir, active)
    return {"running": True, "session": active, "remaining": remaining}


def stop_focus(base_dir: str, complete: bool = True) -> dict:
    """Stop the running session. completed=True (default) marks it finished and
    moves it to the journal; completed=False abandons it."""
    data = _load(base_dir)
    active = data.get("active")
    if not active:
        return {"closed": False, "session": None}
    _close_active(data, "completed" if complete else "abandoned")
    _save(base_dir, data)
    return {"closed": True, "session": active}


def _finish(base_dir: str, active: dict) -> dict:
    data = _load(base_dir)
    if data.get("active", {}).get("id") != active.get("id"):
        # Re-entered concurrently; report the current truth.
        return focus_status(base_dir) if data.get("active") else {"running": False, "session": None, "remaining": 0}
    _close_active(data, "completed")
    _save(base_dir, data)
    return {"running": False, "session": None, "remaining": 0}


def _close_active(data: dict, status: str) -> None:
    active = data.get("active")
    if not active:
        return
    active["status"] = status
    active["ended_at"] = _now()
    data.setdefault("sessions", [])
    data["sessions"].insert(0, active)
    data["sessions"] = data["sessions"][:200]
    data["active"] = None


def focus_journal(base_dir: str, limit: int = 50) -> list:
    data = _load(base_dir)
    return data.get("sessions", [])[:limit]


def compute_daily_minutes(sessions: list) -> dict:
    """Pure helper: {YYYY-MM-DD: minutes} from a session journal (skips
    abandoned, clamps to planned). Shared by today_focus_seconds and the
    Personal Hub heatmap so both always agree."""
    per_day = {}
    for s in sessions:
        if s.get("status") == "abandoned":
            continue
        started = int(s.get("started_at", 0) or 0)
        ended = int(s.get("ended_at", 0) or started)
        planned = int(s.get("minutes", 0) or 0) * 60
        if not started or planned <= 0:
            continue
        spent = max(0, min(ended - started, planned))
        key = datetime.fromtimestamp(started).strftime("%Y-%m-%d")
        per_day[key] = per_day.get(key, 0) + spent // 60
    return per_day


def compute_streaks(per_day: dict) -> tuple[int, int]:
    """(current_streak, longest_streak) from a {date: minutes} map.

    Current streak counts back from today (today with 0 minutes does not
    break it — the day may not be over yet)."""
    import datetime as _dt

    today = _dt.date.today()
    current = 0
    for offset in range(0, 365):
        key = (today - _dt.timedelta(days=offset)).isoformat()
        if per_day.get(key, 0) >= 1:
            current += 1
        elif offset == 0:
            continue
        else:
            break
    longest = run = 0
    for offset in range(364, -1, -1):
        key = (today - _dt.timedelta(days=offset)).isoformat()
        if per_day.get(key, 0) >= 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return current, longest


def today_focus_seconds(base_dir: str) -> int:
    """Completed focus seconds from the local day, for dashboard stats."""
    data = _load(base_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0
    for s in data.get("sessions", []):
        ended = s.get("ended_at")
        if not ended:
            continue
        if datetime.fromtimestamp(ended).strftime("%Y-%m-%d") != today:
            continue
        if s.get("status") == "abandoned":
            continue
        planned = int(s.get("minutes", 0)) * 60
        elapsed = ended - int(s.get("started_at", ended))
        total += max(0, min(elapsed, planned))
    return total
