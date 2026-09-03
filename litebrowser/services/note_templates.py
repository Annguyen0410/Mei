"""Note templates: one-command daily plans and weekly reviews.

Pure composition over the existing services (tasks, calendar, focus,
history) — no new storage. Templates are regular SafeVault markdown
notes, so [[wiki-links]], backlinks and the AI index see them too.
"""
from __future__ import annotations

import time

from litebrowser.core import prefs
from litebrowser.services import (
    focus_service,
    life_service,
    personal_service,
)


def _fmt_ts(ts_value: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_value)) if ts_value else "-"


def create_daily_note(base_dir: str) -> dict:
    """Today's plan: overdue + due-today tasks, today's events, focus."""
    day = time.strftime("%Y-%m-%d")
    title = f"Daily — {day}"
    lines = [f"# Daily — {day}", ""]

    tasks = life_service.load_tasks(base_dir)
    now = int(time.time())
    overdue = [t for t in tasks if not t.get("completed") and 0 < int(t.get("due_at", 0) or 0) <= now]
    due_today = [t for t in tasks if not t.get("completed") and t.get("due_at") and abs(int(t.get("due_at", 0) or 0) - now) < 86400]
    lines.append("## Tasks")
    if overdue:
        lines.append("### Overdue")
        lines.extend(f"- [ ] {t.get('title', '')} — was due {_fmt_ts(int(t.get('due_at', 0) or 0))}" for t in overdue[:10])
    if due_today:
        lines.append("### Due today")
        lines.extend(f"- [ ] {t.get('title', '')}" for t in due_today[:10])
    plain = [t for t in tasks if not t.get("completed") and not t.get("due_at")][:6]
    if plain:
        lines.append("### Sometime")
        lines.extend(f"- [ ] {t.get('title', '')}" for t in plain)
    if not (overdue or due_today or plain):
        lines.append("- Nothing pending. [[Add a task from the omnibar]] with /task")

    events = [e for e in life_service.load_events(base_dir) if int(e.get("starts_at", 0) or 0) >= now - 3600][:8]
    lines.append("")
    lines.append("## Upcoming events")
    if events:
        lines.extend(f"- {e.get('title', '')} — {_fmt_ts(int(e.get('starts_at', 0) or 0))}" for e in events)
    else:
        lines.append("- No events scheduled.")

    minutes = focus_service.today_focus_seconds(base_dir) // 60
    lines.append("")
    lines.append(f"## Focus today: {minutes} min")
    lines.append("")
    lines.append("## Notes for today")
    lines.append("- ")
    return personal_service.create_note(base_dir, title, "\n".join(lines), category="Daily")


def create_weekly_review(base_dir: str) -> dict:
    """Last-7-days review: visit counts per day, focus totals, completed tasks."""
    title = "Weekly Review — " + time.strftime("%Y-%m-%d")
    lines = [f"# Weekly Review — {time.strftime('%Y-%m-%d')}", ""]

    entries = prefs.load_history_entries(base_dir)
    midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    per_day = [0] * 7
    top = {}
    for ts, url in entries:
        ts = int(ts or 0)
        age = int((midnight - ts) // 86400)
        if 0 <= age < 7:
            per_day[6 - age] += 1
            domain = url.split("/")[2] if "://" in url else url[:30]
            top[domain] = top.get(domain, 0) + 1
    lines.append("## Pages visited (last 7 days)")
    days = ["6 days ago", "5 days ago", "4 days ago", "3 days ago", "2 days ago", "yesterday", "today"]
    for label, count in zip(days, per_day):
        bar = "█" * min(24, count // 5 or (1 if count else 0))
        lines.append(f"- {label}: {count} {bar}")
    lines.append("")

    lines.append("## Top sites this week")
    for domain, count in sorted(top.items(), key=lambda kv: -kv[1])[:6]:
        lines.append(f"- {domain} — {count} visits")

    tasks = life_service.load_tasks(base_dir)
    done = [t for t in tasks if t.get("completed")][-10:]
    lines.append("")
    lines.append("## Completed lately")
    if done:
        lines.extend(f"- [x] {t.get('title', '')}" for t in done)
    else:
        lines.append("- Nothing completed yet — /task to start")

    minutes = focus_service.today_focus_seconds(base_dir) // 60
    sessions = focus_service.focus_journal(base_dir)[:7]
    lines.append("")
    lines.append(f"## Focus: {minutes} min today · {len(sessions)} recent pours")
    for s in sessions[:5]:
        lines.append(f"- {s.get('label') or 'pour'} — {s.get('minutes', '?')} min, {s.get('status') or '?'}")
    lines.append("")
    lines.append("## Reflections")
    lines.append("- What went well: ")
    lines.append("- What to change: ")
    lines.append("- Focus for next week: ")
    return personal_service.create_note(base_dir, title, "\n".join(lines), category="Daily")
