"""AI agent actions — let the assistant do small jobs on your local data.

Each action uses the configured AI provider when available and falls back to a
deterministic rule-based implementation otherwise, so the feature always
produces something useful, even fully offline.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from urllib.parse import urlparse

from litebrowser.core import prefs
from litebrowser.services import ai_service, life_service, personal_service


def _ai_answer(base_dir: str, prompt: str) -> str:
    """Ask the configured LLM; return '' when none is reachable."""
    try:
        settings = prefs.load_ai_settings(base_dir)
    except Exception:
        return ""
    provider = (settings.get("provider") or "rag").strip()
    if provider not in ("openrouter", "ollama", "llama_cpp"):
        return ""
    try:
        result = ai_service.answer_query(base_dir, prompt, provider=provider)
        answer = (result or {}).get("answer") or ""
    except Exception:
        return ""
    if not answer or answer.startswith("No related items"):
        return ""
    return answer.strip()


def summarize_tabs(tabs: list[dict], base_dir: str) -> str:
    """Return a Markdown digest of open tabs (AI when available, else by domain)."""
    valid = [t for t in (tabs or []) if (t.get("url") or "").startswith("http")]
    if not valid:
        return "# Tab Summary\n\nNo tabs to summarize."
    listing = "\n".join(f"- {t.get('title') or t.get('url')} — {t.get('url')}" for t in valid)
    ai = _ai_answer(
        base_dir,
        "Summarize the following open browser tabs into a concise markdown digest grouped by topic:\n\n" + listing,
    )
    if ai:
        return f"# Tab Summary\n\n{ai}"

    groups: OrderedDict[str, list] = OrderedDict()
    for t in valid:
        dom = (urlparse(t.get("url")).netloc or "other").lower()
        groups.setdefault(dom, []).append(t.get("title") or t.get("url"))
    lines = [f"# Tab Summary — {len(valid)} tabs", ""]
    for dom, titles in groups.items():
        lines.append(f"## {dom}")
        lines += [f"- {title}" for title in titles]
        lines.append("")
    return "\n".join(lines)


def summarize_tabs_to_note(base_dir: str, tabs: list[dict], title: str = "") -> dict:
    content = summarize_tabs(tabs, base_dir)
    note_title = (title or "").strip() or time.strftime("Tab digest %Y-%m-%d %H:%M")
    return personal_service.create_note(base_dir, note_title, content, category="AI")


def weekly_review(base_dir: str) -> str:
    """A week's digest: history by day, completed tasks, and notes created.
    Rule-based and local-only, so it always works offline."""
    from collections import defaultdict
    from datetime import datetime, timedelta

    week_start = int((datetime.now() - timedelta(days=7)).timestamp())
    history = prefs.load_history_entries(base_dir) or []
    week_history = [(ts, url) for ts, url in history if int(ts or 0) >= week_start]

    by_day: defaultdict[str, list] = defaultdict(list)
    for ts, url in week_history:
        day = datetime.fromtimestamp(int(ts or 0)).strftime("%a %d %b")
        if url.startswith("http"):
            by_day[day].append(url)

    tasks = life_service.load_tasks(base_dir) or []
    completed = [
        t for t in tasks
        if t.get("completed") and int(t.get("updated_at") or t.get("created_at") or 0) >= week_start
    ]
    notes = personal_service.list_notes(base_dir) or []

    lines = [
        f"# Weekly Review — {datetime.now().strftime('%d %B %Y')}",
        "",
        f"- **Pages visited this week**: {len(week_history)}",
        f"- **Tasks completed**: {len(completed)}",
        f"- **Notes in vault**: {len(notes)}",
        "",
    ]
    if by_day:
        lines.append("## Activity by day")
        for day in sorted(by_day):
            lines.append(f"- {day}: {len(by_day[day])} pages")
        lines.append("")
    if completed:
        lines.append("## Completed tasks")
        lines += [f"- {t.get('title', '')}" for t in completed[:10]]
        lines.append("")
    if not week_history and not completed:
        lines.append("A quiet week — nothing tracked since seven days ago.")
    return "\n".join(lines)


def extract_tasks_from_text(base_dir: str, text: str) -> list[dict]:
    """Turn lines / action items into tasks. Deterministic and safe."""
    created = []
    raw = (text or "").replace(";", "\n").replace("|", "\n")
    for line in raw.splitlines():
        line = line.strip().lstrip("-*•·✓").strip()
        if not line or len(line) < 4:
            continue
        if line.startswith(("http", "#", "!")):
            continue
        created.append(life_service.add_task(base_dir, line[:140], bucket="ai"))
    return created
