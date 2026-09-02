import os
import re
import time

from litebrowser.core import prefs
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import write_text_atomic
from litebrowser.services import history_service

NOTE_EXTENSIONS = (".md", ".txt")

_cache = {"notes": None, "base_dir": "", "notes_time": 0, "notes_ttl": 2.0}


def _invalidate_cache():
    _cache["notes"] = None
    _cache["notes_time"] = 0


def _get_cached_notes(base_dir: str) -> list[dict[str, str]]:
    now = time.time()
    if _cache["notes"] is not None and _cache["base_dir"] == base_dir and (now - _cache["notes_time"]) < _cache["notes_ttl"]:
        return _cache["notes"]
    items = []
    with profile_locked(base_dir):
        for root, _dirs, files in os.walk(notes_dir(base_dir)):
            for fn in sorted(files):
                if not fn.lower().endswith(NOTE_EXTENSIONS):
                    continue
                path = os.path.join(root, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    record = _note_record_from_path(base_dir, path, text=text)
                    items.append(record)
                except Exception:
                    continue
    items.sort(key=lambda item: (-int(item["updated_at"]), item["title"].lower()))
    _cache["notes"] = items
    _cache["base_dir"] = base_dir
    _cache["notes_time"] = now
    return items
# Windows-forbidden filename characters only; keep Unicode (e.g. Vietnamese) in folder/title slugs.
_WIN_FORBIDDEN_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def notes_dir(base_dir: str) -> str:
    path = os.path.join(prefs.vault_path(base_dir), "notes")
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_category(category: str) -> str:
    raw = (category or "").strip() or "General"
    raw = raw.replace("\\", "/").strip("/")
    parts = [_safe_name(part) for part in raw.split("/") if part.strip()]
    if not parts:
        return "General"
    return "/".join(parts[:4])


def _note_path(base_dir: str, note_id: str) -> str:
    root = os.path.abspath(notes_dir(base_dir))
    path = os.path.abspath(os.path.join(root, str(note_id or "")))
    return path if path.startswith(root + os.sep) else ""


def _note_record_from_path(base_dir: str, path: str, text: str | None = None):
    rel_id = os.path.relpath(path, notes_dir(base_dir))
    rel_id = rel_id.replace("/", os.sep)
    title = os.path.splitext(os.path.basename(rel_id))[0]
    category = os.path.dirname(rel_id).replace("\\", "/").strip("/") or "General"
    if text is None:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    return {
        "id": rel_id,
        "title": title,
        "category": category,
        "path": path,
        "snippet": text.strip().replace("\n", " ")[:200],
        "content": text,
        "updated_at": str(int(os.path.getmtime(path))),
    }


def _safe_name(title: str) -> str:
    raw = (title or "").strip() or "note"
    raw = _WIN_FORBIDDEN_NAME_RE.sub("-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip(" .") or "note"
    if len(raw) > 80:
        raw = raw[:80].rstrip(" .") or "note"
    return raw


def list_notes(base_dir: str, query: str = "") -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if q:
        items = _get_cached_notes(base_dir)
        return [it for it in items if q in f"{it['title']}\n{it['category']}\n{it['content']}".lower()]
    return list(_get_cached_notes(base_dir))


def read_note(base_dir: str, note_id: str):
    with profile_locked(base_dir):
        path = _note_path(base_dir, note_id)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        record = _note_record_from_path(base_dir, path, text=content)
    return record


def create_note(base_dir: str, title: str, content: str = "", category: str = "General"):
    with profile_locked(base_dir):
        category_path = _normalize_category(category)
        folder = os.path.join(notes_dir(base_dir), *category_path.split("/"))
        os.makedirs(folder, exist_ok=True)
        note_id = os.path.join(*category_path.split("/"), _safe_name(title) + ".md")
        path = _note_path(base_dir, note_id)
        suffix = 2
        while os.path.exists(path):
            note_id = os.path.join(*category_path.split("/"), f"{_safe_name(title)}-{suffix}.md")
            path = _note_path(base_dir, note_id)
            suffix += 1
        write_text_atomic(path, content or "")
    _invalidate_cache()
    history_service.log_event(base_dir, "note", title, "Note created", {"note_id": note_id, "category": category_path})
    return read_note(base_dir, note_id)


def save_note(base_dir: str, note_id: str, content: str) -> bool:
    path = _note_path(base_dir, note_id)
    if not os.path.isfile(path):
        return False
    with profile_locked(base_dir):
        write_text_atomic(path, content or "")
    _invalidate_cache()
    history_service.log_event(base_dir, "note", os.path.splitext(note_id)[0], "Note updated", {"note_id": note_id})
    return True


def update_note(base_dir: str, note_id: str, content: str, category: str | None = None):
    with profile_locked(base_dir):
        note = read_note(base_dir, note_id)
        if not note:
            return None
        target_category = _normalize_category(category or note.get("category") or "General")
        current_category = _normalize_category(note.get("category") or "General")
        target_id = note_id
        if target_category != current_category:
            target_folder = os.path.join(notes_dir(base_dir), *target_category.split("/"))
            os.makedirs(target_folder, exist_ok=True)
            target_id = os.path.join(*target_category.split("/"), os.path.basename(note_id))
            target_path = _note_path(base_dir, target_id)
            if os.path.normcase(target_path) != os.path.normcase(_note_path(base_dir, note_id)):
                # A same-named note in the destination must never be clobbered
                # (v6.4 silently os.replace'd over it — data loss). Suffix like
                # create_note does.
                if os.path.exists(target_path):
                    stem = os.path.splitext(os.path.basename(note_id))[0]
                    suffix = 2
                    while True:
                        target_id = os.path.join(*target_category.split("/"), f"{stem}-{suffix}.md")
                        target_path = _note_path(base_dir, target_id)
                        if not os.path.exists(target_path):
                            break
                        suffix += 1
                os.replace(_note_path(base_dir, note_id), target_path)
                note_id = target_id
        path = _note_path(base_dir, note_id)
        if not os.path.isfile(path):
            return None
        write_text_atomic(path, content or "")
    _invalidate_cache()
    history_service.log_event(base_dir, "note", os.path.splitext(note_id)[0], "Note updated", {"note_id": note_id})
    return read_note(base_dir, note_id)


def delete_note(base_dir: str, note_id: str) -> bool:
    with profile_locked(base_dir):
        path = _note_path(base_dir, note_id)
        if not os.path.isfile(path):
            return False
        os.remove(path)
    _invalidate_cache()
    history_service.log_event(base_dir, "note", os.path.splitext(note_id)[0], "Note deleted", {"note_id": note_id})
    return True


def list_note_categories(base_dir: str) -> list[str]:
    categories = {"General"}
    for item in _get_cached_notes(base_dir):
        categories.add(item.get("category") or "General")
    return sorted(categories, key=lambda value: value.lower())


def list_root_entries(base_dir: str, query: str = "") -> list[dict[str, str]]:
    root = prefs.get_personal_root(base_dir) or ""
    if not root or not os.path.isdir(root):
        return []
    q = (query or "").strip().lower()
    out = []
    for name in sorted(os.listdir(root))[:1000]:
        if q and q not in name.lower():
            continue
        path = os.path.join(root, name)
        out.append({"name": name, "path": path, "kind": "dir" if os.path.isdir(path) else "file"})
    return out
