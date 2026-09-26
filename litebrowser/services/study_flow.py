"""The Mei loop: capture → plan → study → review → reflect, in one place.

Every store in this app already works on its own — the browser clips pages, the
planner owns deadlines, flashcards own recall, Café Focus owns the timer, the
entity-link table owns the graph. What was missing is the thing that reads all of
them together and answers the only question a student actually asks: *what do I
do next?*

This module is that reader. It computes the state of the loop from the stores
that already exist (no new file, no new store, nothing to migrate), names the one
next step, and can move an inbox capture into the planner — the single hand-off
that used to be a manual copy/paste between two task systems.

Home's "▶ Continue", the ``/flow`` command, the Morning Brief's next-step line
and the planner's study hint all render the same ``build_flow`` result, so four
surfaces cannot disagree about what is next. See ``docs/WHY_MEI.md`` for the
longer argument.
"""
from __future__ import annotations

import copy
import hashlib
import os
import time
from datetime import datetime, timedelta

from litebrowser.services import (
    flashcard_service,
    focus_service,
    history_service,
    life_service,
    link_service,
    personal_plan,
    personal_service,
)

# A freshly captured note only nags for cards while it is still warm; older
# notes stay searchable but stop competing with today's work.
CAPTURE_WINDOW_DAYS = 14
BRIEF_CATEGORY = "Brief"

# The reflect step keeps a week of evidence; the proactive nudge stays quiet at
# night and never repeats inside its own gap.
WEEK_REVIEW_DAYS = 7
REMINDER_QUIET_HOURS = (22, 8)
REMINDER_MIN_GAP_MINUTES = 90
REMINDER_STALE_MINUTES = 25

_SPARK_LEVELS = "▁▂▃▄▅▆▇█"

# The loop is a *reader* of six stores plus the note vault, and Home, the brief,
# the planner hint and the AI index all ask it the same question. Memoizing it
# costs one stat() sweep and removes the repeated JSON parsing from the GUI
# thread (build_flow was ~20 ms on a 200-note/120-item profile — every one of
# those calls happened while a button was being pressed). Any write to an input
# changes its mtime, which invalidates the entry, and the 1 s floor keeps a
# burst of refreshes inside one interaction cheap.
_FLOW_CACHE_TTL_SECONDS = 1.0
_flow_cache: dict[str, tuple[float, str, dict]] = {}


def reset_flow_cache() -> None:
    """Forget the memoized loop (call right after a write that must be seen now)."""
    _flow_cache.clear()


def _vault_stamp_rows(root: str) -> list[str]:
    rows = []
    for path in (root, *[os.path.join(root, name) for name in _vault_subdirs(root)]):
        try:
            stat = os.stat(path)
        except OSError:
            rows.append(path)
            continue
        rows.append(f"{path}:{stat.st_mtime_ns}")
    return rows


def _vault_subdirs(root: str) -> list[str]:
    try:
        with os.scandir(root) as entries:
            return sorted(entry.name for entry in entries if entry.is_dir())
    except OSError:
        return []


def _store_stamp(base_dir: str) -> str:
    """Cheap freshness stamp over everything the loop reads.

    Deliberately stats the vault instead of walking it: a new or removed note
    moves its folder's mtime, which is the only note change the loop reacts to
    (adding a note is what creates the "no cards yet" prompt).
    """
    rows: list[str] = []
    for path in (
        life_service.tasks_path(base_dir),
        life_service.calendar_path(base_dir),
        personal_plan.plan_path(base_dir),
        flashcard_service.cards_path(base_dir),
        focus_service.sessions_path(base_dir),
        os.path.join(base_dir, link_service.LINK_FILENAME),
    ):
        try:
            stat = os.stat(path)
        except OSError:
            rows.append(path)
            continue
        rows.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    rows.extend(_vault_stamp_rows(personal_service.notes_dir(base_dir)))
    return hashlib.blake2s("\0".join(rows).encode("utf-8", "surrogatepass"), digest_size=12).hexdigest()


def _memoized(base_dir: str, key: str, compute):
    now = time.monotonic()
    stamp = _store_stamp(base_dir)
    entry = _flow_cache.get(base_dir)
    same_view = bool(entry) and entry[0] > now and entry[1] == stamp
    if same_view and key in entry[2]:
        return copy.deepcopy(entry[2][key])
    value = compute()
    payload = dict(entry[2]) if same_view else {}
    payload[key] = value
    _flow_cache[base_dir] = ((entry[0] if same_view else now + _FLOW_CACHE_TTL_SECONDS), stamp, payload)
    return copy.deepcopy(value)

#: The five stations of the loop, in the order the user walks them.
FLOW_STEPS: tuple[dict, ...] = (
    {
        "key": "capture",
        "title": "Capture",
        "blurb": "Clip a page, note or task into the vault.",
        "hint": "/note · /save-page",
    },
    {
        "key": "plan",
        "title": "Plan",
        "blurb": "Give every captured thing a day and a course.",
        "hint": "Personal → Weekly Plan",
    },
    {
        "key": "study",
        "title": "Study",
        "blurb": "Pour a focus session against the plan; minutes are credited.",
        "hint": "▶ Study · /focus",
    },
    {
        "key": "review",
        "title": "Review",
        "blurb": "Pay the due cards back before they decay.",
        "hint": "/review",
    },
    {
        "key": "reflect",
        "title": "Reflect",
        "blurb": "Read the brief, link what belongs together, save the brief.",
        "hint": "/brief · /flow",
    },
)


def _action(
    step: str,
    label: str,
    reason: str,
    entity_type: str = "",
    entity_id: str = "",
    minutes: int = 0,
    start: bool = False,
) -> dict:
    """One recommendation, shaped so a UI can route it without re-deriving it."""
    return {
        "step": step,
        "label": label,
        "reason": reason,
        "kind": entity_type,
        "id": entity_id,
        "minutes": int(minutes or 0),
        "start": bool(start),
    }


def _find_record(base_dir: str, kind: str, entity_id: str) -> dict:
    plan = personal_plan.load_plan(base_dir)
    if kind == "planner-block":
        for block in plan["time_blocks"]:
            if block.get("id") == entity_id:
                return block
        return {}
    for item in plan["items"]:
        if item.get("id") == entity_id:
            return item
    return {}


def _study_action(base_dir: str, entry: dict, reason: str) -> dict:
    """A Focus pour aimed at one agenda row (item or block)."""
    kind = entry.get("kind", "")
    entity_type = "planner-block" if kind == "planner-block" else "planner-item"
    record = _find_record(base_dir, entity_type, entry.get("id", ""))
    minutes = int(record.get("duration_minutes") or personal_plan.DEFAULT_DURATION_MINUTES)
    subtitle = entry.get("subtitle", "")
    detail = " · ".join(part for part in (reason, subtitle) if part)
    return _action(
        "study",
        f"▶ Study “{entry.get('title', '')}” ({minutes} min)",
        detail,
        entity_type,
        entry.get("id", ""),
        minutes=minutes,
        start=True,
    )


def _pending_items(base_dir: str) -> list[dict]:
    return [item for item in personal_plan.load_plan(base_dir)["items"] if not item.get("completed")]


def _notes_without_cards(base_dir: str) -> list[dict]:
    """Recently captured notes that nobody turned into recall material yet."""
    with_cards = {
        card.get("source_note_id")
        for card in flashcard_service.load_cards(base_dir)
        if card.get("source_note_id")
    }
    cutoff = datetime.now().timestamp() - CAPTURE_WINDOW_DAYS * 86400
    fresh: list[dict] = []
    for note in personal_service.list_notes(base_dir):
        note_id = note.get("id", "")
        if not note_id or note_id in with_cards:
            continue
        if (note.get("category") or "") == BRIEF_CATEGORY:
            continue  # the brief is a digest, not study material
        try:
            updated = float(note.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated = 0.0
        if updated and updated < cutoff:
            continue
        fresh.append(note)
    return fresh


def _unscheduled_items(base_dir: str) -> list[dict]:
    return [
        item
        for item in _pending_items(base_dir)
        if not item.get("scheduled_date") and not item.get("due_date")
    ]


def next_step(base_dir: str) -> dict:
    """The one thing to do now, read from every store at once.

    Order is intentional: a running pour first (never abandon a timer), then the
    planner's late deadlines, then today's classes and blocks, then the review
    debt, then the hand-off from inbox to planner, then fresh captures, and
    finally a calm invitation to shape the week.
    """
    return _memoized(base_dir, "next", lambda: _next_step_uncached(base_dir))


def _next_step_uncached(base_dir: str) -> dict:
    status = focus_service.focus_status(base_dir)
    if status.get("running"):
        remaining = int(status.get("remaining", 0) or 0)
        return _action(
            "study",
            f"Finish your pour — {remaining // 60}m {remaining % 60:02d}s left",
            "A focus session is already running",
        )

    agenda = life_service.today_agenda(base_dir)
    # Only planner rows are study targets: an inbox task has no item to credit, so
    # an overdue capture is a planning problem, not a focus session (it is picked
    # up by the inbox branch below instead).
    overdue = [
        entry
        for entry in agenda["items"]
        if entry.get("overdue") and entry.get("source") == "planner"
    ]
    if overdue:
        return _study_action(base_dir, overdue[0], "Overdue")

    due_today = [
        entry
        for entry in agenda["items"]
        if entry.get("source") == "planner" and entry.get("kind") == "planner-item"
    ]
    if due_today:
        return _study_action(base_dir, due_today[0], "Due today")

    blocks = [entry for entry in agenda["items"] if entry.get("kind") == "planner-block"]
    if blocks:
        return _study_action(base_dir, blocks[0], "Focus block today")

    cards_due = flashcard_service.stats(base_dir)["due"]
    if cards_due:
        return _action(
            "review",
            f"🧠 Review {cards_due} due card(s)",
            "Review debt is waiting in the deck",
        )

    inbox = [entry for entry in agenda["items"] if entry.get("source") == "inbox"]
    if inbox:
        top = next((entry for entry in inbox if entry.get("overdue")), inbox[0])
        return _action(
            "plan",
            f"Plan “{top.get('title', '')}”",
            "Overdue inbox task — promote it into the planner"
            if top.get("overdue")
            else "Inbox capture with no planner home yet",
            "task",
            top.get("id", ""),
        )

    uncarded = _notes_without_cards(base_dir)
    if uncarded:
        return _action(
            "capture",
            f"Turn “{uncarded[0].get('title', '')}” into cards",
            "A captured note has no flashcards yet",
            "note",
            uncarded[0].get("id", ""),
        )

    return _action("plan", "Plan your week", "Nothing is due — give the week a shape")


def build_flow(base_dir: str) -> dict:
    """The whole loop: per-step counts, the next step, and a one-line pulse."""
    return _memoized(base_dir, "flow", lambda: _build_flow_uncached(base_dir))


def _build_flow_uncached(base_dir: str) -> dict:
    agenda = life_service.today_agenda(base_dir)
    cards_due = flashcard_service.stats(base_dir)["due"]
    uncarded = _notes_without_cards(base_dir)
    unscheduled = _unscheduled_items(base_dir)
    inbox_today = [entry for entry in agenda["items"] if entry.get("source") == "inbox"]
    never_studied = [
        item for item in _pending_items(base_dir) if int(item.get("studied_minutes", 0) or 0) <= 0
    ]
    connections = link_service.load_links(base_dir)
    focus_minutes = focus_service.today_focus_seconds(base_dir) // 60

    counts = {
        "capture": len(uncarded),
        "plan": len(unscheduled) + len(inbox_today),
        "study": len(never_studied),
        "review": cards_due,
        "reflect": len(connections),
    }
    details = {
        "capture": f"{len(uncarded)} recent note(s) without cards",
        "plan": f"{len(unscheduled)} unscheduled item(s) · {len(inbox_today)} inbox task(s) today",
        "study": f"{len(never_studied)} item(s) never studied",
        "review": f"{cards_due} card(s) due",
        "reflect": f"{len(connections)} link(s) between notes, cards and the plan",
    }
    steps = [
        {
            "key": step["key"],
            "title": step["title"],
            "blurb": step["blurb"],
            "hint": step["hint"],
            "count": counts[step["key"]],
            "detail": details[step["key"]],
            "ready": counts[step["key"]] > 0,
        }
        for step in FLOW_STEPS
    ]

    action = next_step(base_dir)
    parts: list[str] = []
    if agenda["counts"]["overdue"]:
        parts.append(f"{agenda['counts']['overdue']} overdue")
    if agenda["counts"]["planner"]:
        parts.append(f"{agenda['counts']['planner']} planned today")
    if cards_due:
        parts.append(f"{cards_due} card(s) due")
    if focus_minutes:
        parts.append(f"{focus_minutes} min poured today")
    head = " · ".join(parts) or "Nothing due — the loop is clear"
    pulse = f"{head} · next: {action['label']}" if action else head

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "steps": steps,
        "counts": counts,
        "next": action,
        "pulse": pulse,
        "focus_minutes": focus_minutes,
    }


def reminder(
    base_dir: str,
    last_sent: float = 0.0,
    now: float | None = None,
    min_gap_minutes: int = REMINDER_MIN_GAP_MINUTES,
) -> dict | None:
    """The nudge Mei is allowed to start, or ``None`` when it should stay quiet.

    A reminder is only worth a native toast when it *is* the next step, so this
    is :func:`next_step` plus three restraints: never talk over a running pour,
    never wake the user at night, and never repeat inside the gap. When the loop
    is clear the only thing left worth saying is that nothing has been poured
    today — otherwise silence.
    """
    current = time.time() if now is None else float(now)
    hour = datetime.fromtimestamp(current).hour
    quiet_start, quiet_end = REMINDER_QUIET_HOURS
    quiet = hour >= quiet_start or hour < quiet_end if quiet_start > quiet_end else quiet_start <= hour < quiet_end
    if quiet:
        return None
    gap = max(5, int(min_gap_minutes or REMINDER_MIN_GAP_MINUTES)) * 60
    if last_sent and current - last_sent < gap:
        return None
    if focus_service.focus_status(base_dir).get("running"):
        return None

    action = next_step(base_dir)
    step = action.get("step", "")
    actionable = bool(action.get("id")) or step in ("study", "review")
    if not actionable:
        poured = focus_service.today_focus_seconds(base_dir) // 60
        if poured:
            return None
        return {
            "title": "☕ Nothing poured today",
            "message": "Pick one thing and pour 25 minutes on it — /focus 25",
            "step": "study",
            "id": "",
            "kind": "",
        }
    return {
        "title": f"{step.capitalize() or 'Loop'} reminder",
        "message": f"{action.get('label', '')} — {action.get('reason', '')}".strip(" —"),
        "step": step,
        "id": action.get("id", ""),
        "kind": action.get("kind", ""),
    }


def _sparkline(values: list[int]) -> str:
    """A tiny text chart — one glyph per day, no chart library, no widget."""
    values = [max(0, int(value or 0)) for value in values] or [0]
    top = max(values)
    if top <= 0:
        return _SPARK_LEVELS[0] * len(values)
    span = len(_SPARK_LEVELS) - 1
    return "".join(_SPARK_LEVELS[min(span, int(round(value / top * span)))] for value in values)


def weekly_review(base_dir: str, days: int = WEEK_REVIEW_DAYS, now: float | None = None) -> dict:
    """The reflect step with numbers: what the last week did, and what it skipped.

    Everything here is derived from stores that already exist (the pour journal,
    the planner and the deck), so the digest cannot drift from the surfaces it
    summarizes. ``neglected`` is the honest half: going work that no pour touched
    in the window, worst first.
    """
    window = max(1, min(int(days or WEEK_REVIEW_DAYS), 30))
    moment = datetime.fromtimestamp(time.time() if now is None else float(now))
    if now is not None:
        # An explicit clock means a caller is reasoning about a specific day
        # (tests, imports); never answer that from a cache keyed on the files.
        return _weekly_review(base_dir, window, moment)
    return _memoized(base_dir, f"week:{window}", lambda: _weekly_review(base_dir, window, moment))


def _weekly_review(base_dir: str, window: int, moment: datetime) -> dict:
    day_keys = [(moment.date() - timedelta(days=offset)).isoformat() for offset in range(window - 1, -1, -1)]
    per_day = focus_service.compute_daily_minutes(focus_service.focus_journal(base_dir, limit=200))
    minutes_by_day = {key: int(per_day.get(key, 0) or 0) for key in day_keys}
    current_streak, longest_streak = focus_service.compute_streaks(per_day)

    studies: dict[str, int] = {}
    for session in focus_service.focus_journal(base_dir, limit=200):
        item_id = (session.get("item_id") or "").strip()
        started = int(session.get("started_at", 0) or 0)
        if not item_id or not started or session.get("status") == "abandoned":
            continue
        key = datetime.fromtimestamp(started).strftime("%Y-%m-%d")
        if key not in minutes_by_day:
            continue
        studies[item_id] = studies.get(item_id, 0) + int(session.get("minutes", 0) or 0)

    plan = personal_plan.load_plan(base_dir)
    neglected = []
    for item in plan["items"]:
        item_id = item.get("id", "")
        if not item_id or item.get("completed") or studies.get(item_id):
            continue
        due = (item.get("due_date") or item.get("scheduled_date") or "").strip()
        overdue_days = 0
        if due:
            try:
                overdue_days = max(0, (moment.date() - datetime.fromisoformat(due).date()).days)
            except ValueError:
                overdue_days = 0
        studied = int(item.get("studied_minutes", 0) or 0)
        if overdue_days:
            detail = f"overdue {overdue_days}d"
        elif studied:
            detail = f"{studied} min total, none this week"
        else:
            detail = "never studied"
        neglected.append(
            {
                "kind": "planner-item",
                "id": item_id,
                "title": item.get("title", ""),
                "detail": detail,
                "minutes": int(item.get("duration_minutes") or personal_plan.DEFAULT_DURATION_MINUTES),
                "rank": (overdue_days, item.get("priority") == "urgent", studied),
            }
        )
    neglected.sort(key=lambda row: row["rank"], reverse=True)

    total_minutes = sum(minutes_by_day.values())
    return {
        "days": window,
        "date": moment.strftime("%Y-%m-%d"),
        "minutes_by_day": minutes_by_day,
        "spark": _sparkline([minutes_by_day[key] for key in day_keys]),
        "minutes_total": total_minutes,
        "days_poured": sum(1 for value in minutes_by_day.values() if value > 0),
        "streak": current_streak,
        "longest_streak": longest_streak,
        "items_studied": len(studies),
        "cards_due": flashcard_service.stats(base_dir)["due"],
        "links": len(link_service.load_links(base_dir)),
        "neglected": [
            {key: value for key, value in row.items() if key != "rank"} for row in neglected[:5]
        ],
    }


def review_line(review: dict) -> str:
    """One sentence for the Home card, built from a :func:`weekly_review` result."""
    days = int(review.get("days", WEEK_REVIEW_DAYS) or WEEK_REVIEW_DAYS)
    minutes = int(review.get("minutes_total", 0) or 0)
    poured = int(review.get("days_poured", 0) or 0)
    streak = int(review.get("streak", 0) or 0)
    spark = review.get("spark", "")
    head = f"{spark}  {minutes} min in {days} days · {poured}/{days} days poured"
    if streak:
        head += f" · 🔥 {streak}-day streak"
    neglected = review.get("neglected") or []
    if neglected:
        head += f"\nWaiting on you: {neglected[0].get('title', '')} ({neglected[0].get('detail', '')})"
    elif minutes:
        head += "\nNothing is being left behind — the loop is honest this week."
    else:
        head += "\nNo pours yet this week. Start with one 25-minute block."
    return head


def promote_task(base_dir: str, task_id: str, due_date: str = "") -> dict | None:
    """Move an inbox capture into the planner and link it back to where it came from.

    The inbox keeps the thought; the planner keeps the commitment. The task is
    completed rather than deleted so the link (and the history) still resolves,
    and the same row can be un-completed if the promotion was a mistake.
    """
    task = next(
        (entry for entry in life_service.load_tasks(base_dir) if entry.get("id") == task_id),
        None,
    )
    if task is None:
        return None
    due_at = int(task.get("due_at", 0) or 0)
    bucket = (task.get("bucket") or "").strip().lower()
    if due_at:
        due = due_date or datetime.fromtimestamp(due_at).strftime("%Y-%m-%d")
    elif bucket == "today":
        # An inbox row filed under "today" belongs on today's plan, or the
        # promotion would move it out of the only list that was showing it.
        due = due_date or datetime.now().strftime("%Y-%m-%d")
    else:
        due = due_date
    item = personal_plan.create_item(
        base_dir,
        task.get("title", ""),
        kind="task",
        notes=task.get("notes") or "",
        due_date=due,
        scheduled_date=due,
    )
    if not task.get("completed") and not task.get("archived"):
        life_service.toggle_task(base_dir, task_id)
    link_service.add_link(base_dir, "task", task_id, "planner_item", item["id"], label="promoted")
    history_service.log_event(
        base_dir,
        "plan",
        task.get("title", ""),
        f"Promoted inbox task → planner ({due or 'unscheduled'})",
        {"task_id": task_id, "item_id": item["id"]},
    )
    return item
