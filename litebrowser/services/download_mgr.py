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
    with profile_locked(base_dir):
        items = load_list(base_dir)
        items.append(
            {
                "url": url,
                "path": save_path,
                "filename": filename or os.path.basename(save_path),
                "status": status,
            }
        )
        write_json(_path(base_dir), items)
        history_service.log_event(base_dir, "download", filename or os.path.basename(save_path), "Download started", {"url": url, "path": save_path, "status": status})
        return len(items) - 1


def update_status(base_dir, index, status):
    with profile_locked(base_dir):
        items = load_list(base_dir)
        if 0 <= index < len(items):
            items[index]["status"] = status
            write_json(_path(base_dir), items)
            history_service.log_event(base_dir, "download", items[index].get("filename", ""), f"Download {status}", {"url": items[index].get("url", ""), "path": items[index].get("path", "")})


def remove_download(base_dir, index):
    with profile_locked(base_dir):
        items = load_list(base_dir)
        if 0 <= index < len(items):
            items.pop(index)
            write_json(_path(base_dir), items)
            return True
        return False


def get_download_dir(base_dir):
    return app_paths.downloads_dir(base_dir)
