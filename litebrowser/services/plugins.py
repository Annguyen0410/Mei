"""Plugins — declared, not executed: a contract anybody can add to without asking.

The plan for 1.0 says the "market" should be *doors*, not more in-house features.
Plugins are the mechanism: a plugin is a **JSON manifest**, not a program. It says
what it needs and what it does, Mei does the work, and nothing runs inside the
app that the app did not write itself. That choice buys three things at once:

* nothing to sandbox — there is no code to isolate, so there is no security
  surface to model, and no "install this and hope" moment for the user;
* a manifest can be **validated before it is trusted** (schema, api version,
  legal fields), so a broken plugin is reported instead of half-applied;
* it is honest about what it can do: API 1 defines exactly two kinds,
  ``importer`` and ``exporter``. ``widget`` / ``card_type`` / ``theme`` are *not*
  accepted yet, because nothing would execute them — a kind that does nothing is
  worse than a kind that is absent.

Where they live: ``<profile>/plugins/<id>/plugin.json`` for your own, and
``litebrowser/data/plugins/*.json`` for the ones shipped with the app (two CSV
importers and one exporter today). Discovery never raises: an unreadable or
invalid manifest becomes a *problem* in the report, never a traceback.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field

from litebrowser.services import flashcard_service, life_service, personal_service

#: The contract version this build implements. A manifest asking for a newer one
#: is refused with a message that says so, instead of being half-understood.
PLUGIN_API_VERSION = 1

#: Kinds that actually execute. Nothing is listed here that has no runner.
KINDS = ("importer", "exporter")

#: Where a plugin may read from / write to. Each has an existing store behind it.
TARGETS = {
    "tasks": "Quick tasks",
    "notes": "Notes",
    "cards": "Flashcard deck",
    "saved_pages": "Saved pages",
}

MANIFEST_NAME = "plugin.json"
PROFILE_PLUGINS_DIR = "plugins"
#: The manifests that ship with Mei. Resolved from *this package*, not from the
#: launcher's folder, so a frozen exe and a source checkout agree.
BUILTIN_PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "plugins")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,40}$")

REQUIRED_FIELDS = ("id", "name", "version", "api", "kind")
ALLOWED_FIELDS = frozenset(
    {
        "id",
        "name",
        "version",
        "api",
        "kind",
        "summary",
        "target",
        "format",
        "mapping",
        "builtin",
    }
)


@dataclass(frozen=True)
class Plugin:
    """One accepted manifest, with everything the runner needs to be explicit."""

    id: str
    name: str
    version: str
    kind: str
    target: str
    format: str
    api: int = PLUGIN_API_VERSION
    mapping: dict = field(default_factory=dict)
    summary: str = ""
    path: str = ""
    builtin: bool = False

    def touches(self) -> str:
        """One line for the UI: what this plugin will read or write."""
        where = TARGETS.get(self.target, self.target)
        if self.kind == "importer":
            return f"Adds rows to {where}"
        return f"Writes a file from {where}"


class PluginError(RuntimeError):
    """A manifest that cannot be trusted, or a run that cannot be finished."""


# --------------------------------------------------------------------------- #
# Discovery + validation
# --------------------------------------------------------------------------- #
def _plugin_dirs(base_dir: str) -> list[tuple[str, bool]]:
    """``(directory, is_builtin)`` pairs, user plugins last so they can win."""
    dirs: list[tuple[str, bool]] = [(BUILTIN_PLUGINS_DIR, True)]
    if base_dir:
        dirs.append((os.path.join(base_dir, PROFILE_PLUGINS_DIR), False))
    return dirs


def _validate(raw: dict, path: str, builtin: bool) -> Plugin:
    """Turn one manifest dict into a ``Plugin`` or raise ``PluginError``."""
    if not isinstance(raw, dict):
        raise PluginError("the manifest is not a JSON object")
    missing = [key for key in REQUIRED_FIELDS if not str(raw.get(key, "")).strip()]
    if missing:
        raise PluginError("missing field(s): " + ", ".join(missing))
    unknown = sorted(set(raw) - ALLOWED_FIELDS)
    if unknown:
        raise PluginError("unknown field(s): " + ", ".join(unknown))
    plugin_id = str(raw["id"]).strip()
    if not _ID_RE.match(plugin_id):
        raise PluginError("id must be lowercase letters, digits, dot, dash or underscore")
    try:
        api = int(raw["api"])
    except (TypeError, ValueError) as exc:
        raise PluginError("api must be a number") from exc
    if api > PLUGIN_API_VERSION:
        raise PluginError(f"needs plugin API {api}; this Mei speaks API {PLUGIN_API_VERSION} — update Mei")
    if api < 1:
        raise PluginError("api must be 1 or higher")
    kind = str(raw["kind"]).strip().lower()
    if kind not in KINDS:
        raise PluginError(f"kind must be one of {', '.join(KINDS)} (API {PLUGIN_API_VERSION})")
    target = str(raw.get("target", "")).strip().lower()
    if target not in TARGETS:
        raise PluginError(f"target must be one of {', '.join(sorted(TARGETS))}")
    plugin_format = str(raw.get("format", "csv")).strip().lower()
    if plugin_format != "csv":
        raise PluginError("format must be csv")
    mapping = raw.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise PluginError("mapping must be an object of {field: column header}")
    for key, value in mapping.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PluginError("mapping keys and values must be strings")
    return Plugin(
        id=plugin_id,
        name=str(raw["name"]).strip(),
        version=str(raw["version"]).strip(),
        kind=kind,
        api=api,
        target=target,
        format=plugin_format,
        mapping={str(key).strip(): str(value).strip() for key, value in mapping.items()},
        summary=str(raw.get("summary", "")).strip(),
        path=path,
        builtin=builtin,
    )


def load_plugins(base_dir: str = "") -> dict:
    """Every manifest found, plus a problem list — never raises.

    Returns ``{"plugins": [Plugin, …], "problems": [{"path", "reason"}, …]}``.
    A manifest that cannot be read or validated is a *problem*: the rest still
    load, and the Settings card can show exactly what is wrong with which file.
    """
    plugins: dict[str, Plugin] = {}
    problems: list[dict] = []
    for directory, builtin in _plugin_dirs(base_dir):
        if not os.path.isdir(directory):
            continue
        candidates: list[str] = []
        for name in sorted(os.listdir(directory)):
            folder = os.path.join(directory, name)
            if os.path.isdir(folder):
                candidates.append(os.path.join(folder, MANIFEST_NAME))
            elif name.endswith(".json"):
                candidates.append(folder)
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    raw = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                problems.append({"path": path, "reason": f"cannot be read ({exc})"})
                continue
            try:
                plugin = _validate(raw, path, builtin)
            except PluginError as exc:
                problems.append({"path": path, "reason": str(exc)})
                continue
            plugins[plugin.id] = plugin
    return {"plugins": list(plugins.values()), "problems": problems}


def builtin_plugins() -> list[Plugin]:
    """The manifests that ship with the app (read from ``data/plugins``)."""
    return [plugin for plugin in load_plugins(base_dir="")["plugins"] if plugin.builtin]


def plugins_dir(base_dir: str) -> str:
    """Where this profile's own plugins live (created on demand by the UI)."""
    return os.path.join(base_dir, PROFILE_PLUGINS_DIR)


# --------------------------------------------------------------------------- #
# Running a declarative plugin
# --------------------------------------------------------------------------- #
def _read_rows(path: str) -> tuple[list[dict], list[str]]:
    """Read a CSV into dicts keyed by header, tolerant of a BOM and of ``\\t``."""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = [str(name or "").strip() for name in (reader.fieldnames or [])]
        rows: list[dict] = []
        for row in reader:
            rows.append({str(key or "").strip(): (value or "") for key, value in row.items()})
    return rows, headers


def _pick(row: dict, mapping: dict, field_name: str, fallback: str) -> str:
    column = mapping.get(field_name) or fallback
    if not column:
        return ""
    return str(row.get(column, "") or "").strip()


def _import_tasks(base_dir: str, rows: list[dict], mapping: dict) -> dict:
    added = skipped = 0
    for row in rows:
        title = _pick(row, mapping, "title", "Task")
        if not title:
            skipped += 1
            continue
        notes = _pick(row, mapping, "notes", "Notes") or None
        bucket = _pick(row, mapping, "bucket", "") or "personal"
        life_service.add_task(base_dir, title, bucket=bucket, notes=notes)
        added += 1
    return {"imported": added, "skipped": skipped}


def _import_notes(base_dir: str, rows: list[dict], mapping: dict) -> dict:
    added = skipped = 0
    for row in rows:
        title = _pick(row, mapping, "title", "Title")
        body = _pick(row, mapping, "body", "Body")
        if not title:
            skipped += 1
            continue
        personal_service.create_note(base_dir, title, body, _pick(row, mapping, "category", "Category") or "General")
        added += 1
    return {"imported": added, "skipped": skipped}


def _import_cards(base_dir: str, rows: list[dict], mapping: dict) -> dict:
    added = skipped = 0
    for row in rows:
        front = _pick(row, mapping, "front", "Front")
        back = _pick(row, mapping, "back", "Back")
        if not front or not back:
            skipped += 1
            continue
        flashcard_service.add_card(base_dir, front, back)
        added += 1
    return {"imported": added, "skipped": skipped}


def _import_saved_pages(base_dir: str, rows: list[dict], mapping: dict) -> dict:
    added = skipped = 0
    for row in rows:
        url = _pick(row, mapping, "url", "URL")
        if not url:
            skipped += 1
            continue
        title = _pick(row, mapping, "title", "Title") or url
        life_service.add_saved_page(base_dir, title, url, summary=_pick(row, mapping, "summary", "Summary"))
        added += 1
    return {"imported": added, "skipped": skipped}


_IMPORTERS = {
    "tasks": _import_tasks,
    "notes": _import_notes,
    "cards": _import_cards,
    "saved_pages": _import_saved_pages,
}


def _export_rows(base_dir: str, target: str) -> tuple[list[str], list[dict]]:
    """The columns and rows an exporter will write for one target store."""
    if target == "tasks":
        rows = [
            {"title": task.get("title", ""), "bucket": task.get("bucket", ""), "notes": task.get("notes", "") or ""}
            for task in life_service.load_tasks(base_dir)
        ]
        return ["title", "bucket", "notes"], rows
    if target == "cards":
        rows = [
            {"front": card.get("front", ""), "back": card.get("back", ""), "due": str(card.get("due", ""))}
            for card in flashcard_service.load_cards(base_dir)
        ]
        return ["front", "back", "due"], rows
    if target == "notes":
        rows = [
            {"title": note.get("title", ""), "category": note.get("category", ""), "body": note.get("content", "")}
            for note in personal_service.list_notes(base_dir)
        ]
        return ["title", "category", "body"], rows
    if target == "saved_pages":
        rows = [
            {"title": page.get("title", ""), "url": page.get("url", ""), "summary": page.get("summary", "")}
            for page in life_service.load_saved_pages(base_dir)
        ]
        return ["title", "url", "summary"], rows
    raise PluginError(f"nothing to export for {target}")


def run_plugin(plugin: Plugin, base_dir: str, path: str) -> dict:
    """Run one manifest. Importers read ``path``; exporters write it."""
    if plugin.kind == "importer":
        if not os.path.isfile(path):
            raise PluginError(f"there is no file to read at {path}")
        rows, headers = _read_rows(path)
        runner = _IMPORTERS.get(plugin.target)
        if runner is None:
            raise PluginError(f"no importer for {plugin.target}")
        report = runner(base_dir, rows, plugin.mapping)
        return {
            "plugin": plugin.id,
            "kind": plugin.kind,
            "target": plugin.target,
            "path": path,
            "rows": len(rows),
            "columns": headers,
            **report,
        }
    if plugin.kind == "exporter":
        columns, rows = _export_rows(base_dir, plugin.target)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return {
            "plugin": plugin.id,
            "kind": plugin.kind,
            "target": plugin.target,
            "path": path,
            "rows": len(rows),
            "columns": columns,
            "imported": len(rows),
            "skipped": 0,
        }
    raise PluginError(f"kind {plugin.kind} cannot be run by API {PLUGIN_API_VERSION}")


def report_line(report: dict, plugin: Plugin | None = None) -> str:
    """One sentence for the dialog: what just happened."""
    name = plugin.name if plugin is not None else report.get("plugin", "plugin")
    rows = int(report.get("rows", 0) or 0)
    if report.get("kind") == "exporter":
        return f"{name}: wrote {rows} row(s) to {os.path.basename(report.get('path', ''))}"
    skipped = int(report.get("skipped", 0) or 0)
    line = f"{name}: imported {int(report.get('imported', 0) or 0)} of {rows} row(s)"
    if skipped:
        line += f" — {skipped} skipped (no title)"
    return line


__all__ = [
    "KINDS",
    "PLUGIN_API_VERSION",
    "BUILTIN_PLUGINS_DIR",
    "Plugin",
    "PluginError",
    "TARGETS",
    "builtin_plugins",
    "load_plugins",
    "plugins_dir",
    "report_line",
    "run_plugin",
]
