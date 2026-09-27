"""The desk — the four blocks Home opens on.

Home used to open on a grid of nine launcher tiles plus a row of stat tiles,
which is a *menu*: it tells you what the app can do, never what to do. This
module answers the four questions a person actually sits down with, in one
call, by reading stores that already exist:

===============  ==========================================================
``today``        what is on the plate today (planner + quick inbox)
``due``          what is late, what lands inside the next week, cards due
``in_progress``  what was left open: pages mid-read, items half-studied
``next``         the one next step of the loop (``study_flow``)
===============  ==========================================================

There is no new store and nothing to migrate: the desk is a *view* over the
planner, the quick-task inbox, the deck, the saved pages and the loop. The
launcher grid is not gone — it moved behind Home's "All features" toggle, so
browsing the app is still one click away while sitting down to work is the
default.

``tests/test_desk.py`` pins the four blocks and the rule that ``due`` never
contains anything that is not late or near-due.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from litebrowser.services import (
    flashcard_service,
    life_service,
    personal_plan,
    study_flow,
)

#: The four blocks, in the order they are rendered.
DESK_BLOCKS = ("today", "due", "in_progress", "next")

BLOCK_TITLES = {
    "today": "Today",
    "due": "Due",
    "in_progress": "Unfinished",
    "next": "Next step",
}

BLOCK_SUBTITLES = {
    "today": "Planner deadlines · quick tasks · focus blocks",
    "due": "Late or landing this week · cards to pay back",
    "in_progress": "Half-studied items · pages you were reading",
    "next": "The loop reads every store and names one thing",
}

#: How many rows a block shows before it stops (Home is a desk, not a report).
ROW_LIMIT = 5

#: What an empty block says — one sentence, in the block's own voice.
BLOCK_EMPTY = {
    "today": "Nothing on the plate today",
    "due": "Nothing late, nothing landing this week",
    "in_progress": "Nothing left half-finished",
    "next": "The loop is clear — pour something",
}

#: A deadline inside this window is "due soon" even when it is not late yet.
DUE_HORIZON_DAYS = 7

#: The inbox bucket that means "today" for a task with no due date.
TODAY_BUCKET = "today"


def _row(
    kind: str,
    entity_id: str,
    title: str,
    subtitle: str = "",
    marker: str = "",
    command: str = "",
) -> dict:
    """One line on the desk: routable by the shell, or runnable as a command."""
    return {
        "kind": kind,
        "id": entity_id,
        "title": title,
        "subtitle": subtitle,
        "marker": marker,
        "command": command,
    }


def _block(key: str, rows: list[dict], count: int | None = None, unit: str = "") -> dict:
    block = {
        "key": key,
        "title": BLOCK_TITLES[key],
        "subtitle": BLOCK_SUBTITLES[key],
        "rows": rows[:ROW_LIMIT],
        "count": len(rows) if count is None else int(count),
        "unit": unit,
        "empty": BLOCK_EMPTY.get(key, "Nothing here"),
        "flow": None,
    }
    return block


def _agenda_row(entry: dict) -> dict:
    marker = "⚠ " if entry.get("overdue") else ""
    return _row(
        entry.get("kind", ""),
        entry.get("id", ""),
        entry.get("title", ""),
        entry.get("subtitle", ""),
        marker,
    )


def _deadline_rows(base_dir: str, today_key: str, horizon: str) -> list[dict]:
    """Planner items whose ``due_date`` lands inside the horizon, soonest first."""
    rows: list[dict] = []
    plan = personal_plan.load_plan(base_dir)
    course_names = {
        course.get("id", ""): course.get("name", "")
        for course in plan.get("courses", [])
        if isinstance(course, dict)
    }
    for item in plan.get("items", []):
        if item.get("completed"):
            continue
        due = item.get("due_date") or ""
        if not due or due < today_key or due > horizon:
            continue
        course = course_names.get(item.get("course_id", ""), "")
        days = (datetime.strptime(due, "%Y-%m-%d").date() - datetime.strptime(today_key, "%Y-%m-%d").date()).days
        when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        rows.append(
            _row(
                "planner-item",
                item.get("id", ""),
                item.get("title", ""),
                " · ".join(part for part in (course, item.get("kind", ""), f"due {when}") if part),
                "" if days else "⚠ ",
            )
        )
    rows.sort(key=lambda row: row.get("subtitle", ""))
    return rows


def _in_progress_rows(base_dir: str) -> list[dict]:
    """What was left open — half-studied planner items and pages mid-read."""
    rows: list[dict] = []
    plan = personal_plan.load_plan(base_dir)
    course_names = {
        course.get("id", ""): course.get("name", "")
        for course in plan.get("courses", [])
        if isinstance(course, dict)
    }
    for item in plan.get("items", []):
        if item.get("completed") or int(item.get("studied_minutes", 0) or 0) <= 0:
            continue
        studied = int(item.get("studied_minutes", 0) or 0)
        total = int(item.get("duration_minutes", 0) or 0)
        progress = f"{studied}/{total}m" if total else f"{studied}m"
        rows.append(
            _row(
                "planner-item",
                item.get("id", ""),
                item.get("title", ""),
                " · ".join(
                    part for part in (course_names.get(item.get("course_id", ""), ""), progress, "left open") if part
                ),
                "◐ ",
            )
        )
    page = life_service.continue_reading_page(base_dir)
    if page:
        percent = int(page.get("progress", 0) or 0)
        rows.append(
            _row(
                "saved-page",
                page.get("id", ""),
                page.get("title", "") or page.get("url", ""),
                f"read to {percent}% · {page.get('url', '')}",
                "▸ ",
            )
        )
    return rows


def _due_rows(agenda_items: list[dict], base_dir: str, today_key: str, horizon: str) -> list[dict]:
    rows = [_agenda_row(entry) for entry in agenda_items if entry.get("overdue")]
    rows.extend(_deadline_rows(base_dir, today_key, horizon))
    due_cards = len(flashcard_service.due_cards(base_dir))
    if due_cards:
        rows.append(
            _row(
                "due-cards",
                "",
                f"{due_cards} card{'s' if due_cards != 1 else ''} due",
                "Pay them back before they fade",
                "⇄ ",
                command="/review",
            )
        )
    return rows


def build_desk(base_dir: str, day: str = "") -> dict:
    """The four blocks, plus the loop's pulse line and a one-line headline.

    ``day`` is the ``YYYY-MM-DD`` key the agenda is computed for (tests pin a
    day so a run just after midnight cannot move the answer).
    """
    today_key = day or datetime.now().strftime("%Y-%m-%d")
    horizon = (datetime.strptime(today_key, "%Y-%m-%d").date() + timedelta(days=DUE_HORIZON_DAYS)).isoformat()

    agenda = life_service.today_agenda(base_dir, today_key)
    agenda_items = list(agenda.get("items", []))

    todo_rows = [
        _agenda_row(entry)
        for entry in agenda_items
        if not entry.get("overdue")
        and (entry.get("source") == "planner" or entry.get("subtitle") == TODAY_BUCKET)
    ]
    due_rows = _due_rows(agenda_items, base_dir, today_key, horizon)
    unfinished_rows = _in_progress_rows(base_dir)

    flow = study_flow.build_flow(base_dir)
    action = flow.get("next") or {}
    next_block = _block("next", [], count=1 if action else 0, unit="step left")
    next_block["flow"] = action or None
    next_block["rows"] = [
        _row(
            action.get("kind", ""),
            action.get("id", ""),
            action.get("label", ""),
            action.get("reason", ""),
            "▶ ",
        )
    ] if action else []

    blocks = [
        _block("today", todo_rows, unit="on the plate"),
        _block("due", due_rows, unit="waiting"),
        _block("in_progress", unfinished_rows, unit="left open"),
        next_block,
    ]
    desk = {
        "date": today_key,
        "blocks": blocks,
        "pulse": flow.get("pulse", ""),
        "agenda_counts": agenda.get("counts", {}),
        "steps": [step.get("title", "") for step in flow.get("steps", [])],
    }
    desk["headline"] = desk_headline(desk)
    return desk


def block_by_key(desk: dict, key: str) -> dict:
    """The block with ``key`` from a desk payload (empty dict when absent)."""
    for block in desk.get("blocks", []):
        if block.get("key") == key:
            return block
    return {}


def desk_headline(desk: dict) -> str:
    """One line that says what the desk is looking at, for Home's title area."""
    todo = block_by_key(desk, "today").get("count", 0)
    due = block_by_key(desk, "due").get("count", 0)
    open_items = block_by_key(desk, "in_progress").get("count", 0)
    parts = [
        f"{todo} on the plate" if todo else "nothing on the plate",
        f"{due} waiting" if due else "nothing waiting",
    ]
    if open_items:
        parts.append(f"{open_items} left open")
    return " · ".join(parts)
