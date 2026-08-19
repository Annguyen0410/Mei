"""Persistent, lightweight tab collections.

Collections deliberately store tab *descriptions*, not WebEngine state.  That
keeps saved research sessions inexpensive to keep around and lets the UI
restore inactive tabs in a hibernated state.
"""

import os
import time
import uuid
from collections.abc import Iterable
from typing import Any

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json

SCHEMA_VERSION = 2
VALID_KINDS = {"search", "personal", "ai", "workspace", "collection"}
MAX_TAB_SETS = 80
MAX_AUTO_TAB_SETS = 18
MAX_TITLE_LENGTH = 120


def _clean_text(value: Any, limit: int = MAX_TITLE_LENGTH) -> str:
    return str(value or "").strip().replace("\x00", "")[:limit]


def _normalize_tab(tab: Any) -> dict[str, Any] | None:
    """Return a compact, portable tab payload or ``None`` for invalid rows."""
    if not isinstance(tab, dict):
        return None
    url = _clean_text(tab.get("url"), 4096)
    if not url or url in {"about:blank", "about:newtab"}:
        return None
    return {
        "kind": "tab",
        "url": url,
        "title": _clean_text(tab.get("title") or url, 240),
        "icon": _clean_text(tab.get("icon"), 4096),
        # A restored inactive tab should always be able to start cold.
        "hibernated": bool(tab.get("hibernated", True)),
        "active": bool(tab.get("active")),
        "pinned": bool(tab.get("pinned")),
        "workspace_id": _clean_text(tab.get("workspace_id") or tab.get("workspace"), 80),
        "group": _clean_text(tab.get("group"), 80),
    }


def normalize_tabs(tabs: Iterable[dict]) -> list[dict[str, Any]]:
    """Sanitize collection input while retaining order and intentional duplicates."""
    result = []
    for tab in tabs or []:
        normalized = _normalize_tab(tab)
        if normalized:
            result.append(normalized)
    return result


def _is_auto_snapshot(tab_set: dict[str, Any]) -> bool:
    if bool(tab_set.get("auto")):
        return True
    return _clean_text(tab_set.get("title")).lower().startswith("search auto ")


def _normalize_set(tab_set: Any) -> dict[str, Any] | None:
    if not isinstance(tab_set, dict):
        return None
    tab_id = _clean_text(tab_set.get("id"), 80) or uuid.uuid4().hex
    kind = tab_set.get("kind") if tab_set.get("kind") in VALID_KINDS else "collection"
    title = _clean_text(tab_set.get("title")) or "Untitled collection"
    try:
        created_at = int(tab_set.get("created_at", 0) or 0)
    except (TypeError, ValueError):
        created_at = 0
    try:
        updated_at = int(tab_set.get("updated_at", created_at) or created_at)
    except (TypeError, ValueError):
        updated_at = created_at
    tags = tab_set.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "id": tab_id,
        "kind": kind,
        "title": title,
        "created_at": created_at,
        "updated_at": updated_at,
        "workspace_id": _clean_text(tab_set.get("workspace_id"), 80),
        "note": _clean_text(tab_set.get("note"), 500),
        "tags": [_clean_text(tag, 32) for tag in tags if _clean_text(tag, 32)][:12],
        "auto": _is_auto_snapshot(tab_set),
        "tabs": normalize_tabs(tab_set.get("tabs", [])),
    }


def _trim_sets(tab_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep manual collections and a compact rolling set of automatic snapshots."""
    ordered = sorted(tab_sets, key=lambda item: -int(item.get("updated_at") or item.get("created_at") or 0))
    automatic = [item for item in ordered if _is_auto_snapshot(item)][:MAX_AUTO_TAB_SETS]
    manual = [item for item in ordered if not _is_auto_snapshot(item)]
    return (manual + automatic)[:MAX_TAB_SETS]


def tab_sets_path(base_dir: str) -> str:
    return os.path.join(base_dir, "tab_sets.json")


def load_tab_sets(base_dir: str) -> dict[str, Any]:
    data = read_json(tab_sets_path(base_dir), {"version": SCHEMA_VERSION, "sets": []})
    if not isinstance(data, dict):
        return {"version": SCHEMA_VERSION, "sets": []}
    raw_sets = data.get("sets", [])
    if not isinstance(raw_sets, list):
        raw_sets = []
    normalized = [item for item in (_normalize_set(tab_set) for tab_set in raw_sets) if item]
    return {"version": SCHEMA_VERSION, "sets": _trim_sets(normalized)}


def save_tab_sets(base_dir: str, data: dict[str, Any]) -> None:
    raw_sets = data.get("sets", []) if isinstance(data, dict) else []
    payload = {
        "version": SCHEMA_VERSION,
        "sets": _trim_sets([item for item in (_normalize_set(tab_set) for tab_set in raw_sets) if item]),
    }
    with profile_locked(base_dir):
        write_json(tab_sets_path(base_dir), payload)


def add_tab_set(
    base_dir: str,
    kind: str,
    title: str,
    tabs: list[dict],
    *,
    workspace_id: str = "",
    note: str = "",
    tags: list[str] | None = None,
    auto: bool | None = None,
) -> dict[str, Any]:
    """Save a named collection and return the normalized record.

    Existing callers need only provide the original four arguments.  ``auto``
    is inferred for legacy close-time snapshots, which prevents those snapshots
    from growing forever while protecting user-named collections.
    """
    with profile_locked(base_dir):
        data = load_tab_sets(base_dir)
        normalized_kind = kind if kind in VALID_KINDS else "collection"
        now = int(time.time())
        normalized_title = _clean_text(title) or "Untitled collection"
        tab_set = {
            "id": uuid.uuid4().hex,
            "kind": normalized_kind,
            "title": normalized_title,
            "created_at": now,
            "updated_at": now,
            "workspace_id": _clean_text(workspace_id, 80),
            "note": _clean_text(note, 500),
            "tags": [_clean_text(tag, 32) for tag in (tags or []) if _clean_text(tag, 32)][:12],
            "auto": bool(auto) if auto is not None else normalized_title.lower().startswith("search auto "),
            "tabs": normalize_tabs(tabs),
        }
        data["sets"].append(tab_set)
        payload = {
            "version": SCHEMA_VERSION,
            "sets": _trim_sets(data["sets"]),
        }
        write_json(tab_sets_path(base_dir), payload)
        return tab_set


def list_tab_sets(base_dir: str) -> list[dict[str, Any]]:
    sets = load_tab_sets(base_dir).get("sets", [])
    return sorted(
        sets,
        key=lambda item: -int(item.get("updated_at") or item.get("created_at") or 0),
    ) if isinstance(sets, list) else []


def get_tab_set(base_dir: str, set_id: str) -> dict[str, Any] | None:
    target = _clean_text(set_id, 80)
    return next((item for item in list_tab_sets(base_dir) if item.get("id") == target), None)


def rename_tab_set(base_dir: str, set_id: str, title: str) -> bool:
    normalized_title = _clean_text(title)
    if not normalized_title:
        return False
    with profile_locked(base_dir):
        data = load_tab_sets(base_dir)
        for item in data.get("sets", []):
            if item.get("id") == set_id:
                item["title"] = normalized_title
                item["updated_at"] = int(time.time())
                write_json(tab_sets_path(base_dir), {"version": SCHEMA_VERSION, "sets": _trim_sets(data["sets"])})
                return True
    return False


def remove_tab_set(base_dir: str, set_id: str) -> None:
    with profile_locked(base_dir):
        data = load_tab_sets(base_dir)
        data["sets"] = [item for item in data.get("sets", []) if item.get("id") != set_id]
        payload = {"version": SCHEMA_VERSION, "sets": _trim_sets(data["sets"])}
        write_json(tab_sets_path(base_dir), payload)
