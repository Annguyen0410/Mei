import base64
import json
import os
import time
import urllib.parse
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

    return {
        "id": batch_id,
        "window_id": window_id,
        "source_browser": source_browser,
        "source_label": source_label,
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
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ValueError(f"Could not read import file: {exc}") from exc
    return import_from_json_text(base_dir, text)


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
