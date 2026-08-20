import base64
import json
import os
import time
import urllib.parse
import zipfile
from typing import Any

from litebrowser.core import storage_utils
from litebrowser.core.profile_lock import profile_locked


def storage_path(base_dir: str) -> str:
    return os.path.join(base_dir, "extension_imports.json")


def load_batches(base_dir: str) -> list[dict[str, Any]]:
    data = storage_utils.read_json(storage_path(base_dir), {"batches": []})
    if not isinstance(data, dict):
        return []
    batches = data.get("batches", [])
    return batches if isinstance(batches, list) else []


def save_batches(base_dir: str, batches: list[dict[str, Any]]) -> None:
    payload = {"version": 1, "batches": batches if isinstance(batches, list) else []}
    with profile_locked(base_dir):
        storage_utils.write_json(storage_path(base_dir), payload)


def _normalize_tab(tab: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tab, dict):
        return None
    url = str(tab.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://", "file://")):
        return None
    return {
        "url": url,
        "title": str(tab.get("title") or url).strip() or url,
        "active": bool(tab.get("active", False)),
        "pinned": bool(tab.get("pinned", False)),
    }


def _normalize_batch(payload: dict[str, Any]) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    tabs = [_normalize_tab(tab) for tab in (payload.get("tabs") or [])]
    tabs = [tab for tab in tabs if tab]
    if not tabs:
        raise ValueError("Payload does not contain any importable tabs.")

    batch_id = str(payload.get("batch_id") or payload.get("id") or f"ext_{now_ms}")
    created_at = int(payload.get("created_at") or payload.get("captured_at") or now_ms)
    imported_at = payload.get("imported_at")
    window_id = str(payload.get("window_id") or payload.get("source_window_id") or "unknown")
    source_browser = str(payload.get("source_browser") or payload.get("browser") or "chrome-family").strip() or "chrome-family"
    source_label = str(payload.get("source_label") or f"Window {window_id}").strip() or f"Window {window_id}"
    # Which monitor/screen this window was on (0-based). Mei uses it to split a
    # multi-screen export back into separate workspaces.
    try:
        screen_index = int(payload.get("screen_index", payload.get("window_index", -1)))
    except (TypeError, ValueError):
        screen_index = -1

    return {
        "id": batch_id,
        "window_id": window_id,
        "source_browser": source_browser,
        "source_label": source_label,
        "screen_index": screen_index,
        "created_at": created_at,
        "imported_at": imported_at,
        "tab_count": len(tabs),
        "tabs": tabs,
    }


def upsert_batch(base_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    with profile_locked(base_dir):
        batch = _normalize_batch(payload)
        batches = load_batches(base_dir)
        replaced = False
        for idx, existing in enumerate(batches):
            if existing.get("id") == batch["id"]:
                batches[idx] = batch
                replaced = True
                break
        if not replaced:
            batches.insert(0, batch)
        storage_utils.write_json(storage_path(base_dir), {"version": 1, "batches": batches[:100]})
        return batch


def import_from_json_text(base_dir: str, text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("batches"), list):
        imported = None
        for batch_payload in payload["batches"]:
            imported = upsert_batch(base_dir, batch_payload)
        if imported is None:
            raise ValueError("Payload contains no batches.")
        return imported
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")
    return upsert_batch(base_dir, payload)


def import_from_file(base_dir: str, path: str) -> dict[str, Any]:
    if not path or not os.path.isfile(path):
        raise ValueError("Import file was not found.")
    if path.lower().endswith(".zip"):
        return import_from_zip(base_dir, path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ValueError(f"Could not read import file: {exc}") from exc
    return import_from_json_text(base_dir, text)


def import_from_zip(base_dir: str, path: str) -> dict[str, Any]:
    """Import a .zip exported by the Mei bridge extension.

    Two layouts are accepted:

    1. The extension's own layout — a ``workspace.json`` manifest with a
       ``batches`` array (one entry per monitor/screen), plus optional
       ``screen-N.json`` files. The manifest is authoritative.
    2. A plain folder of ``*.json`` batch files (any names), each imported as
       its own window batch.

    Returns the last batch imported (mirrors ``import_from_json_text``), or
    raises ValueError when the archive has no importable tabs.
    """
    if not path or not os.path.isfile(path):
        raise ValueError("Import file was not found.")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid ZIP archive: {exc}") from exc

    try:
        names = [n for n in archive.namelist() if n.lower().endswith(".json")]
        if not names:
            raise ValueError("ZIP archive contains no .json files.")

        last = None
        # Extension manifest takes priority when present.
        manifest_names = [n for n in names if os.path.basename(n).lower() == "workspace.json"]
        if manifest_names:
            try:
                text = archive.read(manifest_names[0]).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"workspace.json is not valid UTF-8: {exc}") from exc
            payload = json.loads(text)
            batches = payload.get("batches") if isinstance(payload, dict) else None
            if not isinstance(batches, list) or not batches:
                raise ValueError("workspace.json has no batches array.")
            for batch_payload in batches:
                last = upsert_batch(base_dir, batch_payload)
            return last

        # Fall back to every JSON file in the archive, in name order (so
        # screen-1.json < screen-2.json keeps the monitor ordering).
        for name in sorted(names):
            try:
                text = archive.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("batches"), list):
                for batch_payload in payload["batches"]:
                    last = upsert_batch(base_dir, batch_payload)
            elif isinstance(payload, dict):
                last = upsert_batch(base_dir, payload)
        if last is None:
            raise ValueError("ZIP archive contains no importable tab batches.")
        return last
    finally:
        archive.close()


def import_from_encoded_query(base_dir: str, encoded: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        json_text = urllib.parse.unquote(decoded)
        payload = json.loads(json_text)
    except Exception as exc:
        raise ValueError("Could not decode importBatchData payload.") from exc

    if isinstance(payload, list):
        payload = {
            "id": f"query_{int(time.time() * 1000)}",
            "source_browser": "query-import",
            "source_label": "Query Import",
            "tabs": payload,
        }
    if not isinstance(payload, dict):
        raise ValueError("Decoded import payload is invalid.")
    return upsert_batch(base_dir, payload)


def mark_batch_imported(base_dir: str, batch_id: str) -> None:
    batches = load_batches(base_dir)
    now_ms = int(time.time() * 1000)
    changed = False
    for batch in batches:
        if batch.get("id") == batch_id:
            batch["imported_at"] = now_ms
            changed = True
            break
    if changed:
        save_batches(base_dir, batches)
