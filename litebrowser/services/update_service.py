import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from litebrowser.core import app_version


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    download_url: str
    notes: str
    published_at: str
    has_update: bool


def _normalize_version(version: str):
    parts = []
    for chunk in str(version or "").strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _read_remote_json(url: str, timeout: int = 8):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{app_version.APP_NAME}/{app_version.APP_VERSION}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read().decode(charset, errors="replace")
    return json.loads(payload)


def check_for_updates(metadata_url: str | None = None) -> UpdateInfo:
    """Check for updates. Raises a clear error if no update server is configured.

    ``metadata_url`` lets tests point at a fixture server without touching the
    global default; when empty we fall back to the app version's configured URL.
    """
    url = metadata_url or app_version.UPDATE_METADATA_URL
    if not url:
        raise ValueError(
            "Update server is not configured in this build. "
            "Set LITEBROWSER_UPDATE_METADATA_URL when publishing."
        )
    metadata = _read_remote_json(url)
    latest_version = str(metadata.get("version") or "").strip()
    if not latest_version:
        raise ValueError("Missing version in update metadata")

    download_url = str(
        metadata.get("download_url")
        or metadata.get("installer_url")
        or metadata.get("release_url")
        or app_version.RELEASES_PAGE_URL
    ).strip()
    notes = str(metadata.get("notes") or metadata.get("changelog") or "").strip()
    published_at = str(metadata.get("published_at") or metadata.get("date") or "").strip()
    current_version = app_version.APP_VERSION
    has_update = _normalize_version(latest_version) > _normalize_version(current_version)
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        download_url=download_url,
        notes=notes,
        published_at=published_at,
        has_update=has_update,
    )


def download_update_package(download_url: str, version: str) -> str:
    if not download_url:
        raise ValueError("Missing download URL")
    target_dir = os.path.join(tempfile.gettempdir(), app_version.APP_NAME, "updates")
    os.makedirs(target_dir, exist_ok=True)
    file_name = f"{app_version.APP_NAME}-{version}.exe"
    target_path = os.path.join(target_dir, file_name)
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": f"{app_version.APP_NAME}/{app_version.APP_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response, open(target_path, "wb") as output:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            output.write(chunk)
    return target_path


def install_downloaded_update(package_path: str) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-replace only supports a built .exe.")
    if not os.path.isfile(package_path):
        raise FileNotFoundError(package_path)

    current_exe = os.path.abspath(sys.executable)
    current_pid = os.getpid()
    script_dir = tempfile.mkdtemp(prefix="litebrowser-updater-")
    script_path = os.path.join(script_dir, "apply_update.cmd")
    script = f"""@echo off
setlocal
set "TARGET={current_exe}"
set "SOURCE={package_path}"
set "PID={current_pid}"

:wait_loop
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

copy /Y "%SOURCE%" "%TARGET%" >nul
start "" "%TARGET%"
del "%SOURCE%" >nul 2>nul
(goto) 2>nul & del "%~f0"
"""
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(script)
    subprocess.Popen(["cmd.exe", "/c", script_path], close_fds=True)


def format_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"Server returned HTTP error {exc.code}."
    if isinstance(exc, urllib.error.URLError):
        return "Could not connect to the update server."
    if isinstance(exc, TimeoutError):
        return "Update check timed out."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Update error: {exc}"
