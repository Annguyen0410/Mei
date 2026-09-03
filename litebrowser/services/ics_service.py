"""Calendar ICS interop: stdlib-only parser/writer for VEVENT files.

Import maps SUMMARY→title, DTSTART→starts_at (unix), DESCRIPTION→notes.
Recurrence (RRULE) is out of scope by design — single events only; Google
Calendar's exported .ics files still import fine for plain events.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from litebrowser.services import life_service


def _parse_ics_dt(raw: str) -> int:
    """VALUE=DATE-TIME forms: 20260903T090000Z, 20260903T090000 (local), 20260903 (all-day)."""
    raw = raw.strip()
    if raw.endswith("Z"):
        try:
            dt = datetime.strptime(raw[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    if "T" in raw:
        try:
            dt = datetime.strptime(raw, "%Y%m%dT%H%M%S")
            return int(dt.astimezone().timestamp())
        except ValueError:
            return 0
    try:
        dt = datetime.strptime(raw, "%Y%m%d")
        return int(dt.astimezone().timestamp())
    except ValueError:
        return 0


def _unfold(text: str) -> list[str]:
    """ICS folds long lines with CRLF + space; unfold before parsing."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_ics(text: str) -> list[dict]:
    events = []
    current = None
    for line in _unfold(text):
        if line.strip() == "BEGIN:VEVENT":
            current = {}
            continue
        if line.strip() == "END:VEVENT":
            if current and current.get("title") and current.get("starts_at"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.split(";")[0].upper()
        value = value.strip()
        if key == "SUMMARY":
            current["title"] = value[:200]
        elif key == "DTSTART":
            current["starts_at"] = _parse_ics_dt(value)
        elif key == "DESCRIPTION":
            current["notes"] = re.sub(r"\\n", "\n", value)[:2000]
    return events


def import_ics_file(base_dir: str, path: str) -> int:
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        events = parse_ics(fh.read())
    count = 0
    for event in events:
        life_service.add_event(base_dir, event["title"], event["starts_at"], bucket="imported")
        count += 1
    return count


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def export_ics_file(base_dir: str, path: str) -> int:
    now = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Mei//Calendar//EN",
    ]
    count = 0
    for event in life_service.load_events(base_dir):
        starts = int(event.get("starts_at", 0) or 0)
        if not starts:
            continue
        dt = datetime.utcfromtimestamp(starts) + timedelta(hours=0)
        stamp = dt.strftime("%Y%m%dT%H%M%SZ")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:mei-{event.get('id', 'x')}@mei.local",
            f"DTSTAMP:{now}",
            f"DTSTART:{stamp}",
            f"SUMMARY:{_ics_escape(event.get('title', 'Event'))}",
            f"DESCRIPTION:{_ics_escape(event.get('notes') or '')}",
            "END:VEVENT",
        ])
        count += 1
    lines.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\r\n".join(lines) + "\r\n")
    return count
