"""One inventory of the profile stores Mei understands.

Backup, restore and integrity scanning must agree about a store's filename,
category and root shape.  Keeping that knowledge in one table avoids the usual
drift where a new service writes ``foo.json`` but the backup never sees it and
the integrity scanner calls it unknown.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoreDescriptor:
    """A profile JSON store, described without importing its service module."""

    name: str
    category: str
    root: str  # "list" or "dict"
    collection: str = ""  # dict key holding the row list
    id_key: str = "id"
    version_key: str = "version"
    #: Category used by the Restore Center for selective restore.
    restore_group: str = ""
    #: Whether an absent file is a normal state rather than a finding.
    optional: bool = True


#: The files a backup/restore is allowed to touch.  This is an allowlist, not a
#: directory walk: secrets.dat, BrowserData, proxy_config.json, caches and temp
#: files are deliberately absent.
STORES: tuple[StoreDescriptor, ...] = (
    StoreDescriptor("prefs.json", "preferences", "dict", restore_group="preferences"),
    StoreDescriptor("profile_meta.json", "preferences", "dict", restore_group="preferences"),
    StoreDescriptor("tasks.json", "tasks", "list", restore_group="tasks"),
    StoreDescriptor("calendar.json", "calendar", "list", restore_group="calendar"),
    StoreDescriptor("boards.json", "boards", "list", restore_group="boards"),
    StoreDescriptor("saved_pages.json", "saved_pages", "list", restore_group="saved_pages"),
    StoreDescriptor("bookmarks.json", "bookmarks", "list", restore_group="bookmarks"),
    StoreDescriptor("bookmark_folders.json", "bookmarks", "list", restore_group="bookmarks"),
    StoreDescriptor("flashcards.json", "flashcards", "dict", collection="cards", restore_group="flashcards"),
    StoreDescriptor(
        "personal_plan.json",
        "planner",
        "dict",
        collection="items",
        restore_group="planner",
    ),
    StoreDescriptor("tab_sets.json", "research", "dict", collection="sets", restore_group="research"),
    StoreDescriptor("workspaces.json", "workspaces", "dict", restore_group="workspaces"),
    StoreDescriptor("workspace.json", "workspaces", "dict", restore_group="workspaces"),
    # The link service persists ``{"version": ..., "links": [...]}``.  The
    # catalog used to say "list", which made backup refuse a healthy store.
    StoreDescriptor("entity_links.json", "links", "dict", collection="links", restore_group="links"),
    StoreDescriptor("permissions.json", "permissions", "dict", restore_group="permissions"),
    StoreDescriptor("routines.json", "routines", "dict", collection="routines", restore_group="routines"),
    StoreDescriptor("feeds.json", "feeds", "dict", collection="feeds", restore_group="feeds"),
    StoreDescriptor("monitors.json", "monitors", "dict", collection="monitors", restore_group="monitors"),
    StoreDescriptor("focus_sessions.json", "focus", "dict", restore_group="focus"),
    StoreDescriptor("ai_settings.json", "ai_settings", "dict", restore_group="preferences"),
    StoreDescriptor("ai_index.json", "ai_index", "dict", restore_group="ai_index"),
    StoreDescriptor("extensions.json", "extensions", "dict", restore_group="extensions"),
    StoreDescriptor("extension_imports.json", "extensions", "dict", restore_group="extensions"),
    StoreDescriptor("downloads_list.json", "downloads", "list", restore_group="downloads"),
    # Durable conflict copies are user data.  They deliberately live under
    # Recovery/, but are an explicit allowlist entry: the rest of Recovery
    # (quarantine, staging, journals) stays out of ordinary backups.
    StoreDescriptor(
        "Recovery/conflicts.json",
        "sync_conflicts",
        "dict",
        collection="conflicts",
        restore_group="sync_conflicts",
    ),
)

STORES_BY_NAME = {descriptor.name: descriptor for descriptor in STORES}
RESTORE_GROUPS = tuple(sorted({descriptor.restore_group for descriptor in STORES if descriptor.restore_group}))

#: Never copied recursively into a backup.  ``Recovery`` contains quarantine
#: copies, restore staging and journals; only the explicit conflict allowlist
#: entry above is copied from that directory.
EXCLUDED_NAMES = frozenset(
    {
        "secrets.dat",
        "proxy_config.json",
        "BrowserData",
        "Recovery",
        "Cache",
        "cache",
        "GPUCache",
        "Code Cache",
        "logs",
        "favicons",
        "Downloads",
    }
)


def descriptor_for(name: str) -> StoreDescriptor | None:
    return STORES_BY_NAME.get(name)


#: Stores whose transforms are already persisted through
#: ``core.migration_journal``.  This is intentionally a short, auditable list:
#: a store is not called "migration managed" merely because it is versioned.
JOURNALED_STORES = frozenset({"personal_plan.json", "tab_sets.json", "entity_links.json"})


def migration_coverage() -> dict:
    """Exact, non-aspirational migration/recovery coverage for the catalog."""
    rows = []
    for descriptor in STORES:
        name = descriptor.name.replace("\\", "/")
        if name in JOURNALED_STORES:
            manager = "storespec"
            migration = "journaled versioned transform"
            journal = "durable snapshot + journal"
        elif name == "Recovery/conflicts.json":
            manager = "legacy"
            migration = "merge-only import (no schema transform)"
            journal = "backup/restore transaction; merge is idempotent"
        else:
            manager = "legacy"
            migration = "no active versioned transform"
            journal = "backup + byte-quarantine + write guard"
        rows.append(
            {
                "name": name,
                "manager": manager,
                "migration": migration,
                "journal": journal,
                "backup": "eligible" if name != "Recovery/conflicts.json" else "explicit category",
                "future_schema": "read-only" if descriptor.root == "dict" else "not versioned",
                "recovery": "verified backup / record restore" if name not in ("Recovery/conflicts.json",) else "merge archive / keep both",
            }
        )
    journaled = sum(1 for row in rows if row["manager"] == "storespec")
    return {
        "stores": rows,
        "total": len(rows),
        "journaled": journaled,
        "legacy": len(rows) - journaled,
        "journaled_percent": round((journaled / len(rows)) * 100, 1) if rows else 0.0,
        "notes": {
            "name": "SafeVault/notes",
            "manager": "file-store",
            "migration": "no JSON schema",
            "journal": "backup + per-file atomic writes",
            "backup": "eligible",
            "future_schema": "not applicable",
            "recovery": "record restore / verified backup",
        },
    }


__all__ = [
    "EXCLUDED_NAMES",
    "JOURNALED_STORES",
    "RESTORE_GROUPS",
    "STORES",
    "STORES_BY_NAME",
    "StoreDescriptor",
    "descriptor_for",
    "migration_coverage",
]
