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

from datetime import datetime

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
