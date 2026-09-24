"""Self-update: check a product-owned channel, verify the package, install it safely.

The channel can be remote *or* a build dropped next to the exe: put
``update\\update.json`` + ``Mei.exe`` in the folder beside the running build and the
app offers it on the next launch, replaces itself, keeps one ``.bak`` for rollback
and deletes the old build to free the space back.

Three guarantees this module now enforces (each one was violated before):

1. **Channel ownership** — the metadata must declare ``"product": "mei"``.  The
   desktop app previously polled the LinkLumina web app's channel, read version
   ``6.2.4``, considered it newer than Mei ``0.6.9.0`` and offered to install a
   completely different product over ``Mei.exe``.
2. **Package identity** — the download URL must point at ``Mei.exe`` and the
   downloaded file must be a plausible Windows executable (size + MZ header), so
   an HTML error page can never be written over the running app.
3. **Reversibility** — installing keeps a ``.bak`` next to the executable and a
   watchdog script restores it when the new build fails to come up.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from litebrowser.core import app_version, product
from litebrowser.core.log import get_logger

_log = get_logger("update")

# Metadata key that ties a release channel to a product.
PRODUCT_FIELD = "product"

# A hand-dropped build lives here, next to the exe.  Publishing an update for a
# machine without a release server is then just "copy two files into update\\".
LOCAL_CHANNEL_DIRNAME = "update"
LOCAL_CHANNEL_FILENAME = "update.json"

# Leftovers a previous build/update leaves beside the exe.  ``.bak`` is what the
# rollback keeps; the rest are from interrupted swaps and hand-made copies.
STALE_SUFFIXES = (".bak", ".old", ".new")
STALE_PREFIXES = ("~",)

# Never delete something younger than this: an update that is happening right
# now would otherwise lose its own package mid-flight.
CLEANUP_MIN_AGE_SECONDS = 600


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    download_url: str
    notes: str
    published_at: str
    has_update: bool
    product: str = ""


def _normalize_version(version: str):
    """Split a dotted version into ints; non-numeric chunks become 0."""
    parts = []
    for chunk in str(version or "").strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _version_is_newer(latest: str, current: str) -> bool:
    """Compare two versions of *different* lengths correctly.

    ``(0, 6, 9)`` must not be treated as newer than ``(0, 6, 9, 0)`` just because
    the tuple is shorter/longer — pad both to the same width first.
    """
    left, right = _normalize_version(latest), _normalize_version(current)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


def asset_name(url: str) -> str:
    return os.path.basename(urllib.parse.urlparse(str(url or "")).path)


def app_directory(app_dir: str = "") -> str:
    """Folder the running build lives in (``dist\\`` for a built .exe).

    Empty for a from-source run, so a stray ``update\\`` folder next to
    ``python.exe`` can never hijack a developer's update check.
    """
    if app_dir:
        return os.path.abspath(app_dir)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return ""


def local_channel_path(app_dir: str = "") -> str:
    """``update\\update.json`` beside the exe, when someone dropped one there."""
    directory = app_directory(app_dir)
    if not directory:
        return ""
    path = os.path.join(directory, LOCAL_CHANNEL_DIRNAME, LOCAL_CHANNEL_FILENAME)
    return path if os.path.isfile(path) else ""


def local_channel_packages(app_dir: str = "") -> list[str]:
    """Builds sitting in ``update\\`` — deleted after they are installed."""
    directory = app_directory(app_dir)
    if not directory:
        return []
    folder = os.path.join(directory, LOCAL_CHANNEL_DIRNAME)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, name)
        for name in sorted(os.listdir(folder))
        if name.lower().endswith(".exe") and os.path.isfile(os.path.join(folder, name))
    ]


def local_channel_url(app_dir: str = "") -> str:
    path = local_channel_path(app_dir)
    return f"file:{urllib.request.pathname2url(path)}" if path else ""


def local_source(url: str) -> str:
    """Filesystem path when ``url`` points at a local file, else ``""``.

    Accepts ``file:///D:/...`` *and* a bare Windows path, because a hand-made
    channel JSON is easier to write with ``"D:\\\\builds\\\\Mei.exe"`` in it.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme == "file":
        return urllib.request.url2pathname(parsed.path)
    if parsed.scheme in ("http", "https", "ftp"):
        return ""
    # ``D:\x\Mei.exe`` parses as scheme "d"; anything with no scheme at all (or a
    # single letter) is still a path on this machine.
    return text if len(parsed.scheme) <= 1 else ""


def asset_is_ours(download_url: str) -> bool:
    """True when the download URL points at this product's release asset."""
    name = asset_name(download_url)
    return bool(name) and name.lower() == product.ASSET_NAME.lower()


def _read_remote_json(url: str, timeout: int = 8):
    local = local_source(url)
    if local:
        with open(local, "rb") as handle:
            return json.loads(handle.read().decode("utf-8-sig", errors="replace"))
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


def _wrong_channel_error(declared: str) -> ValueError:
    served = declared or "an unidentified product"
    return ValueError(
        f"This update channel serves {served}, not {product.PRODUCT_NAME}. "
        f"Point {product.PRODUCT_ID} at its own release channel "
        f"(see core/product.py → DEFAULT_UPDATE_CHANNEL_URL) and try again."
    )


def check_for_updates(metadata_url: str | None = None, app_dir: str = "") -> UpdateInfo:
    """Check for updates. Raises a clear error if no update server is configured.

    ``metadata_url`` lets tests point at a fixture server without touching the
    global default; when empty we fall back to the product's configured channel.
    ``app_dir`` overrides ``update\\`` discovery (tests, tooling).
    """
    # A build dropped into ``update\`` beside the exe is a deliberate, local
    # instruction — honour it before the configured remote channel.
    url = metadata_url or local_channel_url(app_dir) or app_version.UPDATE_METADATA_URL
    if not url:
        raise ValueError(
            "Update server is not configured in this build. "
            "Set LITEBROWSER_UPDATE_METADATA_URL when publishing."
        )
    metadata = _read_remote_json(url)
    if not isinstance(metadata, dict):
        raise ValueError("Update metadata is not a JSON object")

    # Ownership gate: a release channel that does not name this product is not
    # ours, no matter how its version number compares.
    declared = str(metadata.get(PRODUCT_FIELD) or "").strip()
    if declared != product.PRODUCT_ID:
        raise _wrong_channel_error(declared)

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
    has_update = _version_is_newer(latest_version, current_version)

    if has_update and download_url and not asset_is_ours(download_url):
        raise ValueError(
            f"The channel offers '{asset_name(download_url)}' for {latest_version}, "
            f"but {product.PRODUCT_NAME} updates ship as {product.ASSET_NAME}. "
            "Refusing an update that is not this product's build."
        )

    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        download_url=download_url,
        notes=notes,
        published_at=published_at,
        has_update=has_update,
        product=declared,
    )


def download_update_package(download_url: str, version: str) -> str:
    if not download_url:
        raise ValueError("Missing download URL")
    if not asset_is_ours(download_url):
        raise ValueError(
            f"Refusing to download '{asset_name(download_url)}' — "
            f"{product.PRODUCT_NAME} updates ship as {product.ASSET_NAME}."
        )
    target_dir = os.path.join(tempfile.gettempdir(), app_version.APP_NAME, "updates")
    os.makedirs(target_dir, exist_ok=True)
    file_name = f"{app_version.APP_NAME}-{version}.exe"
    target_path = os.path.join(target_dir, file_name)
    local = local_source(download_url)
    if local:
        # Already on this machine: copy, never move — the user's build stays put,
        # and the swap script is the only thing allowed to delete it.
        shutil.copyfile(local, target_path)
        return target_path
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


def verify_package(package_path: str) -> None:
    """Reject anything that cannot be a real build before it touches the exe.

    A truncated download, an HTML error page saved as ``.exe`` or a random file
    would otherwise be copied over the running application.
    """
    if not os.path.isfile(package_path):
        raise FileNotFoundError(package_path)
    size = os.path.getsize(package_path)
    if size < product.MIN_PACKAGE_BYTES:
        raise ValueError(
            f"Downloaded update is only {size} bytes — far too small to be "
            f"{product.PRODUCT_NAME}. The download likely failed."
        )
    with open(package_path, "rb") as handle:
        if handle.read(2) != b"MZ":
            raise ValueError(
                "Downloaded update is not a Windows executable (missing MZ header). "
                "Refusing to install it."
            )


def _stale_beside_exe(directory: str) -> list[str]:
    """Leftover swaps next to the exe (and inside ``update\\``), never the live one."""
    live = os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else ""
    found: list[str] = []
    for folder in (directory, os.path.join(directory, LOCAL_CHANNEL_DIRNAME)):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not os.path.isfile(path) or os.path.abspath(path) == live:
                continue
            lower = name.lower()
            if lower.endswith(STALE_SUFFIXES) or (lower.endswith(".exe") and lower.startswith(STALE_PREFIXES)):
                found.append(path)
    return found


def _downloaded_packages() -> list[str]:
    """Update packages this app downloaded into ``%TEMP%\\Mei\\updates``."""
    folder = os.path.join(tempfile.gettempdir(), app_version.APP_NAME, "updates")
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, name)
        for name in sorted(os.listdir(folder))
        if os.path.isfile(os.path.join(folder, name))
    ]


def cleanup_old_artifacts(
    app_dir: str = "",
    *,
    min_age_seconds: int = CLEANUP_MIN_AGE_SECONDS,
    downloaded: bool = True,
) -> dict:
    """Delete what previous builds and updates left behind; report the space freed.

    A self-update is supposed to be space-neutral: the swap keeps one ``.bak`` for
    the rollback window and downloads a ~170 MB copy of the installer.  The swap
    script deletes both on success, but a rollback or a crash leaves them behind,
    so this sweeps them on the next launch.  Anything younger than
    ``min_age_seconds`` is skipped — that is this machine's *current* update.
    """
    directory = app_directory(app_dir)
    candidates = _stale_beside_exe(directory) if directory else []
    if downloaded:
        candidates.extend(_downloaded_packages())

    removed: list[str] = []
    errors: list[str] = []
    freed = 0
    now = time.time()
    for path in candidates:
        try:
            if min_age_seconds and now - os.path.getmtime(path) < min_age_seconds:
                continue
            size = os.path.getsize(path)
            os.remove(path)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        removed.append(path)
        freed += size

    if removed:
        _log.info(
            "cleaned %s stale build file(s), freeing %.0f MB",
            len(removed),
            freed / (1024 * 1024),
        )
    for problem in errors:
        _log.debug("could not clean %s", problem)
    return {"removed": removed, "freed_bytes": freed, "errors": errors}


def _update_script(current_exe: str, package_path: str, pid: int, stale_paths=()) -> str:
    # The old build and the hand-dropped package are dead weight once the new one
    # has come up, so the success branch removes them with the backup.
    cleanup = "".join(f'del "{path}" >nul 2>nul\r\n' for path in stale_paths)

    return f"""@echo off
setlocal
set "TARGET={current_exe}"
set "SOURCE={package_path}"
set "BAK=%TARGET%.bak"
set "PID={pid}"
for %%A in ("%TARGET%") do set "IMAGE=%%~nxA"

:wait_loop
tasklist /FI "PID eq %PID%" | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

copy /Y "%TARGET%" "%BAK%" >nul 2>nul
copy /Y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 goto rollback

start "" "%TARGET%"
timeout /t 15 /nobreak >nul
tasklist /FI "IMAGENAME eq %IMAGE%" | find /I "%IMAGE%" >nul
if errorlevel 1 goto rollback

del "%BAK%" >nul 2>nul
del "%SOURCE%" >nul 2>nul
{cleanup}goto done

:rollback
if exist "%BAK%" copy /Y "%BAK%" "%TARGET%" >nul 2>nul
start "" "%TARGET%"

:done
(goto) 2>nul & del "%~f0"
"""


def install_downloaded_update(package_path: str, stale_paths=()) -> None:
    verify_package(package_path)
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-replace only supports a built .exe.")

    current_exe = os.path.abspath(sys.executable)
    script_dir = tempfile.mkdtemp(prefix="mei-updater-")
    script_path = os.path.join(script_dir, "apply_update.cmd")
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(_update_script(current_exe, package_path, os.getpid(), stale_paths))
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
