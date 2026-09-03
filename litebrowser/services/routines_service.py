"""Routines: local jobs that run inside Mei on a schedule.

routines.json (per profile): {"version": 1, "routines": [
  {"id": "...", "name": "Morning setup", "time": "07:30", "days": [0,1,2,3,4],
   "actions": ["/template daily", "https://school.edu/schedule"], "enabled": true}
]}

`days` use weekday numbers 0=Monday..6=Sunday. Actions starting with "/" run
through the omnibar pipeline; anything else that looks like a URL opens a tab.
A 30 s timer on the primary shell fires due routines once (last_fired guard).
"""
from __future__ import annotations

import os
import time

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, "routines.json")


def _normal_time(value) -> str:
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return "07:30"
    hh, mm = int(parts[0]), int(parts[1])
    return f"{max(0, min(23, hh)):02d}:{max(0, min(59, mm)):02d}"


def load_routines(base_dir: str) -> list[dict]:
    data = read_json(_path(base_dir), {"version": 1, "routines": []})
    routines = data.get("routines") if isinstance(data, dict) else None
    if not isinstance(routines, list):
        return []
    out = []
    for r in routines:
        if not isinstance(r, dict):
            continue
        out.append({
            "id": str(r.get("id") or os.urandom(6).hex()),
            "name": str(r.get("name") or "Routine")[:80],
            "time": _normal_time(r.get("time")),
            "days": [int(d) % 7 for d in r.get("days", []) if isinstance(d, int)],
            "actions": [str(a).strip() for a in r.get("actions", []) if str(a).strip()][:8],
            "enabled": bool(r.get("enabled", True)),
            "last_fired": str(r.get("last_fired") or ""),
        })
    return out


def save_routines(base_dir: str, routines: list[dict]) -> None:
    with profile_locked(base_dir):
        write_json(_path(base_dir), {"version": 1, "routines": routines})


def mark_fired(base_dir: str, routine_id: str, stamp: str) -> None:
    routines = load_routines(base_dir)
    for r in routines:
        if r["id"] == routine_id:
            r["last_fired"] = stamp
    save_routines(base_dir, routines)


def due_routines(base_dir: str, now: time.struct_time | None = None) -> list[dict]:
    """Routines whose time matches now, this weekday, and not yet fired today."""
    now = now or time.localtime()
    today_key = time.strftime("%Y-%m-%d", now)
    clock = time.strftime("%H:%M", now)
    weekday = (now.tm_wday + 0) % 7  # Qt-less stdlib: Monday=0
    out = []
    for r in load_routines(base_dir):
        if not r["enabled"]:
            continue
        if r["days"] and weekday not in r["days"]:
            continue
        if r["time"] != clock:
            continue
        if r["last_fired"] == today_key:
            continue
        out.append(r)
    return out


def add_routine(base_dir: str, name: str, clock: str, days: list[int], actions: list[str]) -> dict:
    routines = load_routines(base_dir)
    routine = {
        "id": os.urandom(6).hex(),
        "name": (name or "Routine").strip()[:80],
        "time": _normal_time(clock),
        "days": sorted({int(d) % 7 for d in days}),
        "actions": [str(a).strip() for a in actions if str(a).strip()][:8],
        "enabled": True,
        "last_fired": "",
    }
    routines.append(routine)
    save_routines(base_dir, routines)
    return routine


def delete_routine(base_dir: str, routine_id: str) -> bool:
    routines = load_routines(base_dir)
    kept = [r for r in routines if r["id"] != routine_id]
    if len(kept) == len(routines):
        return False
    save_routines(base_dir, kept)
    return True
