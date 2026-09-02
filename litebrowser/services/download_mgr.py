import os

from litebrowser.core import app_paths, prefs
from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json
from litebrowser.services import history_service


def _path(base_dir):
    return prefs.downloads_list_path(base_dir)


def load_list(base_dir):
    data = read_json(_path(base_dir), [])
    return data if isinstance(data, list) else []


def save_list(base_dir, items):
    with profile_locked(base_dir):
        write_json(_path(base_dir), items if isinstance(items, list) else [])


def add_download(base_dir, url, save_path, filename=None, status="downloading"):
    """Returns a stable download id (not a list index): a concurrent add from
    the Android bridge used to shift indices so updates landed on the wrong
    entry (v6.4 bug)."""
    with profile_locked(base_dir):
        items = load_list(base_dir)
        next_id = 1 + max((int(it.get("id", 0) or 0) for it in items if isinstance(it, dict)), default=0)
        items.append(
            {
                "id": next_id,
                "url": url,
                "path": save_path,
                "filename": filename or os.path.basename(save_path),
                "status": status,
            }
        )
        write_json(_path(base_dir), items)
        history_service.log_event(base_dir, "download", filename or os.path.basename(save_path), "Download started", {"url": url, "path": save_path, "status": status})
        return next_id


def update_status(base_dir, download_id, status):
    with profile_locked(base_dir):
        items = load_list(base_dir)
        for item in items:
            if isinstance(item, dict) and item.get("id") == download_id:
                item["status"] = status
                write_json(_path(base_dir), items)
                history_service.log_event(base_dir, "download", item.get("filename", ""), f"Download {status}", {"url": item.get("url", ""), "path": item.get("path", "")})
                return True
        return False


def remove_download(base_dir, download_id):
    with profile_locked(base_dir):
        items = load_list(base_dir)
        kept = [it for it in items if not (isinstance(it, dict) and it.get("id") == download_id)]
        if len(kept) == len(items):
            return False
        write_json(_path(base_dir), kept)
        return True


def get_download_dir(base_dir):
    return app_paths.downloads_dir(base_dir)
