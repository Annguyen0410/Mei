"""Weekly student planner data service.

The planner is intentionally stored separately from the legacy task/calendar
files while its model settles.  This keeps existing Personal Hub behavior and
old backups compatible, but gives the weekly planner one normalized contract
for assignments, tasks, courses, and time blocks.
"""
from __future__ import annotations

import copy
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json

PLAN_VERSION = 1
PLAN_FILENAME = "personal_plan.json"
VALID_ITEM_KINDS = ("task", "assignment", "exam", "project", "study")
VALID_PRIORITIES = ("low", "medium", "high", "urgent")
DEFAULT_DURATION_MINUTES = 50
MAX_TITLE_LENGTH = 240
MAX_NOTES_LENGTH = 8000
MAX_TAGS = 24


def plan_path(base_dir: str) -> str:
    return os.path.join(base_dir, PLAN_FILENAME)


def _today() -> date:
    return date.today()


def _date_string(value: Any, *, default: str = "") -> str:
    """Return an ISO date, or ``default`` for invalid/empty input."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return default


def _week_monday(value: Any = None) -> date:
    parsed = _date_string(value, default=_today().isoformat())
    current = date.fromisoformat(parsed)
    return current - timedelta(days=current.weekday())


def week_key(value: Any = None) -> str:
    """Return the Monday ISO date used as a stable weekly-plan key."""
    return _week_monday(value).isoformat()


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_tags(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    seen = set()
    for raw in value:
        tag = _clean_text(raw, 48)
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
        if len(result) >= MAX_TAGS:
            break
    return result


def _clean_priority(value: Any) -> str:
    priority = str(value or "medium").strip().lower()
    return priority if priority in VALID_PRIORITIES else "medium"


def _clean_kind(value: Any) -> str:
    kind = str(value or "task").strip().lower()
    return kind if kind in VALID_ITEM_KINDS else "task"


def _clean_minutes(value: Any, default: int = DEFAULT_DURATION_MINUTES) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = default
    return max(5, min(24 * 60, minutes))


def _normalize_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    now = datetime.now().isoformat(timespec="seconds")
    item_id = _clean_text(item.get("id"), 80) or uuid.uuid4().hex
    title = _clean_text(item.get("title"), MAX_TITLE_LENGTH)
    if not title:
        return None
    scheduled_date = _date_string(item.get("scheduled_date"))
    due_date = _date_string(item.get("due_date"))
    start_minutes = item.get("start_minutes")
    if start_minutes in (None, ""):
        start_minutes = None
    else:
        try:
            start_minutes = max(0, min(1439, int(start_minutes)))
        except (TypeError, ValueError):
            start_minutes = None
    normalized = {
        "id": item_id,
        "kind": _clean_kind(item.get("kind")),
        "title": title,
        "course_id": _clean_text(item.get("course_id"), 80),
        "scheduled_date": scheduled_date,
        "due_date": due_date,
        "start_minutes": start_minutes,
        "duration_minutes": _clean_minutes(item.get("duration_minutes")),
        "priority": _clean_priority(item.get("priority")),
        "category": _clean_text(item.get("category"), 80) or "General",
        "tags": _clean_tags(item.get("tags")),
        "recurrence": _clean_text(item.get("recurrence"), 80),
        "notes": _clean_text(item.get("notes"), MAX_NOTES_LENGTH),
        "completed": bool(item.get("completed", False)),
        "created_at": _clean_text(item.get("created_at"), 40) or now,
        "updated_at": now,
    }
    return normalized


def _normalize_course(course: Any) -> dict | None:
    if not isinstance(course, dict):
        return None
    name = _clean_text(course.get("name") or course.get("title"), 160)
    if not name:
        return None
    return {
        "id": _clean_text(course.get("id"), 80) or uuid.uuid4().hex,
        "name": name,
        "code": _clean_text(course.get("code"), 40),
        "color": _clean_text(course.get("color"), 20) or "#c39d63",
        "schedule": _clean_text(course.get("schedule"), 500),
        "credits": _clean_text(course.get("credits"), 20),
        "created_at": _clean_text(course.get("created_at"), 40) or datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _normalize_block(block: Any) -> dict | None:
    if not isinstance(block, dict):
        return None
    block_date = _date_string(block.get("date") or block.get("scheduled_date"))
    title = _clean_text(block.get("title"), MAX_TITLE_LENGTH)
    if not block_date or not title:
        return None
    try:
        start = max(0, min(1439, int(block.get("start_minutes", 0))))
    except (TypeError, ValueError):
        start = 0
    return {
        "id": _clean_text(block.get("id"), 80) or uuid.uuid4().hex,
        "title": title,
        "date": block_date,
        "start_minutes": start,
        "duration_minutes": _clean_minutes(block.get("duration_minutes")),
        "course_id": _clean_text(block.get("course_id"), 80),
        "item_id": _clean_text(block.get("item_id"), 80),
        "color": _clean_text(block.get("color"), 20) or "#c39d63",
        "created_at": _clean_text(block.get("created_at"), 40) or datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _default_plan() -> dict:
    return {
        "version": PLAN_VERSION,
        "academic_week_start": "monday",
        "semester": {"name": "", "start_date": "", "end_date": ""},
        "items": [],
        "courses": [],
        "time_blocks": [],
    }


def _normalize_plan(data: Any) -> dict:
    source = data if isinstance(data, dict) else {}
    plan = _default_plan()
    semester = source.get("semester")
    if isinstance(semester, dict):
        plan["semester"] = {
            "name": _clean_text(semester.get("name"), 160),
            "start_date": _date_string(semester.get("start_date")),
            "end_date": _date_string(semester.get("end_date")),
        }
    plan["academic_week_start"] = "monday"
    plan["items"] = [normalized for raw in source.get("items", []) for normalized in [_normalize_item(raw)] if normalized]
    plan["courses"] = [normalized for raw in source.get("courses", []) for normalized in [_normalize_course(raw)] if normalized]
    plan["time_blocks"] = [normalized for raw in source.get("time_blocks", []) for normalized in [_normalize_block(raw)] if normalized]
    return plan


def load_plan(base_dir: str) -> dict:
    """Load and normalize the plan, returning a detached mutable copy."""
    return copy.deepcopy(_normalize_plan(read_json(plan_path(base_dir), _default_plan())))


def save_plan(base_dir: str, plan: dict) -> dict:
    normalized = _normalize_plan(plan)
    with profile_locked(base_dir):
        write_json(plan_path(base_dir), normalized)
    return copy.deepcopy(normalized)


def update_plan_settings(base_dir: str, *, semester: dict | None = None) -> dict:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        if isinstance(semester, dict):
            plan["semester"] = {
                "name": _clean_text(semester.get("name"), 160),
                "start_date": _date_string(semester.get("start_date")),
                "end_date": _date_string(semester.get("end_date")),
            }
        write_json(plan_path(base_dir), _normalize_plan(plan))
    return load_plan(base_dir)


def create_item(base_dir: str, title: str, **fields) -> dict:
    item = _normalize_item({"id": uuid.uuid4().hex, "title": title, **fields})
    if item is None:
        raise ValueError("A planner item needs a title")
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        plan["items"].append(item)
        write_json(plan_path(base_dir), _normalize_plan(plan))
    return item


def update_item(base_dir: str, item_id: str, **changes) -> dict | None:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        for index, current in enumerate(plan["items"]):
            if current.get("id") != item_id:
                continue
            merged = dict(current)
            merged.update(changes)
            merged["id"] = item_id
            updated = _normalize_item(merged)
            if updated is None:
                return None
            plan["items"][index] = updated
            write_json(plan_path(base_dir), _normalize_plan(plan))
            return updated
    return None


def complete_item(base_dir: str, item_id: str, completed: bool = True) -> dict | None:
    return update_item(base_dir, item_id, completed=bool(completed))


def delete_item(base_dir: str, item_id: str) -> bool:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        before = len(plan["items"])
        plan["items"] = [item for item in plan["items"] if item.get("id") != item_id]
        plan["time_blocks"] = [block for block in plan["time_blocks"] if block.get("item_id") != item_id]
        if len(plan["items"]) == before:
            return False
        write_json(plan_path(base_dir), _normalize_plan(plan))
        return True


def create_course(base_dir: str, name: str, **fields) -> dict:
    course = _normalize_course({"id": uuid.uuid4().hex, "name": name, **fields})
    if course is None:
        raise ValueError("A course needs a name")
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        plan["courses"].append(course)
        write_json(plan_path(base_dir), _normalize_plan(plan))
    return course


def update_course(base_dir: str, course_id: str, **changes) -> dict | None:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        for index, current in enumerate(plan["courses"]):
            if current.get("id") != course_id:
                continue
            merged = dict(current)
            merged.update(changes)
            merged["id"] = course_id
            updated = _normalize_course(merged)
            if updated is None:
                return None
            plan["courses"][index] = updated
            write_json(plan_path(base_dir), _normalize_plan(plan))
            return updated
    return None


def delete_course(base_dir: str, course_id: str) -> bool:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        before = len(plan["courses"])
        plan["courses"] = [course for course in plan["courses"] if course.get("id") != course_id]
        if len(plan["courses"]) == before:
            return False
        for item in plan["items"]:
            if item.get("course_id") == course_id:
                item["course_id"] = ""
        for block in plan["time_blocks"]:
            if block.get("course_id") == course_id:
                block["course_id"] = ""
        write_json(plan_path(base_dir), _normalize_plan(plan))
        return True


def create_time_block(base_dir: str, title: str, block_date: Any, start_minutes: int, **fields) -> dict:
    block = _normalize_block({
        "id": uuid.uuid4().hex,
        "title": title,
        "date": block_date,
        "start_minutes": start_minutes,
        **fields,
    })
    if block is None:
        raise ValueError("A time block needs a valid date and title")
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        plan["time_blocks"].append(block)
        write_json(plan_path(base_dir), _normalize_plan(plan))
    return block


def update_time_block(base_dir: str, block_id: str, **changes) -> dict | None:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        for index, current in enumerate(plan["time_blocks"]):
            if current.get("id") != block_id:
                continue
            merged = dict(current)
            merged.update(changes)
            merged["id"] = block_id
            updated = _normalize_block(merged)
            if updated is None:
                return None
            plan["time_blocks"][index] = updated
            write_json(plan_path(base_dir), _normalize_plan(plan))
            return updated
    return None


def delete_time_block(base_dir: str, block_id: str) -> bool:
    with profile_locked(base_dir):
        plan = load_plan(base_dir)
        before = len(plan["time_blocks"])
        plan["time_blocks"] = [block for block in plan["time_blocks"] if block.get("id") != block_id]
        if len(plan["time_blocks"]) == before:
            return False
        write_json(plan_path(base_dir), _normalize_plan(plan))
        return True


def items_for_week(base_dir: str, anchor: Any = None) -> dict:
    """Return week metadata, scheduled items, due items, and time blocks."""
    monday = _week_monday(anchor)
    sunday = monday + timedelta(days=6)
    start_key, end_key = monday.isoformat(), sunday.isoformat()
    plan = load_plan(base_dir)
    items = []
    for item in plan["items"]:
        scheduled = item.get("scheduled_date") or ""
        due = item.get("due_date") or ""
        if start_key <= scheduled <= end_key or start_key <= due <= end_key:
            items.append(item)
    blocks = [block for block in plan["time_blocks"] if start_key <= block.get("date", "") <= end_key]
    items.sort(key=lambda item: (item.get("scheduled_date") or item.get("due_date") or "9999-99-99", item.get("start_minutes") is None, item.get("start_minutes") or 0, item.get("priority") or "medium", item.get("title", "").casefold()))
    blocks.sort(key=lambda block: (block.get("date", ""), block.get("start_minutes", 0)))
    return {
        "week_start": start_key,
        "week_end": end_key,
        "items": copy.deepcopy(items),
        "time_blocks": copy.deepcopy(blocks),
        "courses": copy.deepcopy(plan["courses"]),
        "semester": copy.deepcopy(plan["semester"]),
    }
