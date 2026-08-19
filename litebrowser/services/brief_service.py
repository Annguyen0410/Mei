"""Morning Brief — a local-first daily digest assembled from your own data.

No cloud. Reads history, tasks, events, notes, and focus minutes to build a
short "good morning" briefing in the spirit of a café opening note. Rule-based
so it works offline; the AI can dress it up later if a provider is configured.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from litebrowser.browser.new_tab_page import cafe_greeting
from litebrowser.core import prefs
from litebrowser.services import focus_service, life_service, personal_service


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
        return host.removeprefix("www.")
    except Exception:
        return ""


def top_domains(entries, limit: int = 5) -> list:
    counts: Counter = Counter()
    for _ts, url in entries:
        dom = _domain(url)
        if dom:
            counts[dom] += 1
    return counts.most_common(limit)


def build_morning_brief(base_dir: str) -> dict:
    """Return a structured briefing dict. Cheap + deterministic (no network)."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    yesterday_start = today_start - 86400
    now_ts = now.timestamp()

    history = prefs.load_history_entries(base_dir) or []
    yesterday = [(ts, url) for ts, url in history if yesterday_start <= ts < today_start]
    today_visits = [(ts, url) for ts, url in history if ts >= today_start]

    tasks = life_service.load_tasks(base_dir) or []
    pending = [t for t in tasks if not t.get("completed") and not t.get("archived")]
    overdue = [t for t in pending if int(t.get("due_at") or 0) and int(t.get("due_at")) < now_ts]
    overdue_ids = {t.get("id") for t in overdue}
    due_today = [
        t for t in pending
        if t.get("due_at") and today_start <= int(t.get("due_at")) < today_start + 86400
        and t.get("id") not in overdue_ids
    ]

    events = life_service.load_events(base_dir) or []
    upcoming = sorted(
        (e for e in events if int(e.get("starts_at") or 0) >= now_ts),
        key=lambda e: int(e.get("starts_at") or 0),
    )[:3]

    notes = personal_service.list_notes(base_dir) or []
    focus_min = focus_service.today_focus_seconds(base_dir) // 60

    eyebrow, headline = cafe_greeting(now.hour)

    return {
        "date": now.strftime("%A, %d %B %Y"),
        "eyebrow": eyebrow,
        "headline": headline,
        "yesterday_count": len(yesterday),
        "top_domains": top_domains(yesterday, 5),
        "today_visits": len(today_visits),
        "pending_tasks": len(pending),
        "overdue_tasks": [t.get("title", "") for t in overdue],
        "due_today": [t.get("title", "") for t in due_today],
        "upcoming_events": [
            {"title": e.get("title", ""), "starts_at": int(e.get("starts_at") or 0)} for e in upcoming
        ],
        "notes_count": len(notes),
        "focus_minutes": focus_min,
    }


def brief_markdown(brief: dict) -> str:
    """Render the briefing as a Markdown note."""
    lines = [
        f"# ☕ {brief.get('headline', 'Good morning')}",
        f"_{brief.get('date', '')}_",
        "",
    ]
    lines.append(f"- **Yesterday**: {brief.get('yesterday_count', 0)} pages visited.")
    domains = brief.get("top_domains") or []
    if domains:
        lines.append(f"- **Top sites**: {', '.join(f'{d} ({c})' for d, c in domains[:4])}.")
    lines.append(f"- **Today**: {brief.get('today_visits', 0)} pages so far.")
    lines.append(f"- **Focus**: {brief.get('focus_minutes', 0)} min poured today.")
    lines.append(f"- **Notes**: {brief.get('notes_count', 0)} in the vault.")
    lines.append("")

    overdue = brief.get("overdue_tasks") or []
    if overdue:
        lines.append("## ⏰ Overdue")
        lines += [f"- {t}" for t in overdue[:5]]
        lines.append("")

    due_today = brief.get("due_today") or []
    if due_today:
        lines.append("## 📌 Due today")
        lines += [f"- {t}" for t in due_today[:5]]
        lines.append("")

    events = brief.get("upcoming_events") or []
    if events:
        lines.append("## 📅 Coming up")
        for event in events:
            when = time.strftime("%H:%M", time.localtime(event["starts_at"]))
            lines.append(f"- {when} · {event['title']}")
        lines.append("")

    lines.append(f"**{brief.get('pending_tasks', 0)} open tasks** in total.")
    return "\n".join(lines)


def brief_text(brief: dict) -> str:
    """Short plain-text version for the Home card header."""
    parts = []
    if brief.get("overdue_tasks"):
        parts.append(f"⏰ {len(brief['overdue_tasks'])} overdue")
    if brief.get("due_today"):
        parts.append(f"📌 {len(brief['due_today'])} due today")
    if brief.get("upcoming_events"):
        parts.append(f"📅 {brief['upcoming_events'][0]['title']}")
    if brief.get("yesterday_count"):
        domains = brief.get("top_domains") or []
        dom_str = f" mostly {domains[0][0]}" if domains else ""
        parts.append(f"🧭 {brief['yesterday_count']} pages yesterday{dom_str}")
    if brief.get("focus_minutes"):
        parts.append(f"☕ {brief['focus_minutes']} min focus")
    return " · ".join(parts) or "A quiet morning. Pour a cup and start."
