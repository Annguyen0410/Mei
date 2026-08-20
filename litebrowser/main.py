"""Application entry: profile selection, WebEngine flags, QApplication, AppShell windows."""
import os
import shutil
import sys
from urllib.parse import unquote


def _force_software_rendering() -> bool:
    """Opt-in only: set LITEBROWSER_SOFTWARE_RENDERING=1 if GPU drivers crash the app."""
    return os.environ.get("LITEBROWSER_SOFTWARE_RENDERING", "").strip().lower() in ("1", "true", "yes")


if _force_software_rendering():
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_ANGLE_PLATFORM", "software")
    # Software fallback (opt-in only) also forces the Qt Quick scene-graph to
    # rasterize on the CPU. Keep the GPU path enabled by default so web content
    # is composited by the GPU like Chrome/Opera instead of the CPU.
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QApplication, QWidget

from litebrowser.core import app_paths, app_version, prefs
from litebrowser.services import android_bridge_service, workspace_manager
from litebrowser.ui.app_shell import AppShell
from litebrowser.ui.dialogs import show_profiles_dialog


def _saved_proxy_chromium_flag(app_dir: str) -> str:
    """Build the --proxy-server flag for QtWebEngine from the active profile's saved VPN.

    QtWebEngine uses Chromium's networking stack; QNetworkProxy.setApplicationProxy()
    only affects QNetworkAccessManager, NOT page loads. To actually route the WebEngine
    through a proxy we have to pass --proxy-server on launch. Returns "" when no proxy
    is enabled so we don't accidentally break browsing.
    """
    try:
        last = prefs.get_last_profile(app_dir)
        if not last:
            return ""
        profile_dir = os.path.join(prefs.profiles_dir(app_dir), last)
        cfg_path = prefs.proxy_config_path(profile_dir)
        if not os.path.isfile(cfg_path):
            return ""
        import json as _json
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = _json.load(fh)
        if not cfg.get("enabled"):
            return ""
        host = (cfg.get("host") or "").strip()
        port = int(cfg.get("port") or 0)
        if not host or port <= 0 or port > 65535:
            return ""
        scheme = "socks5" if (cfg.get("type") or "http").lower().startswith("socks") else "http"
        # Authenticated proxies: Chromium accepts user:pass inline in the flag.
        from urllib.parse import quote
        user = (cfg.get("user") or "").strip()
        password = (cfg.get("password") or "").strip()
        auth = ""
        if user:
            auth = quote(user, safe="") + (":" + quote(password, safe="") if password else "") + "@"
        return "--proxy-server=%s://%s%s:%d" % (scheme, auth, host, port)
    except Exception:
        return ""


def _get_profile_dir(app_dir):
    last = prefs.get_last_profile(app_dir)
    profiles_d = prefs.profiles_dir(app_dir)
    if last and os.path.isdir(os.path.join(profiles_d, last)):
        return prefs.ensure_profile_layout(os.path.join(profiles_d, last))
    names = prefs.list_profiles(app_dir)
    if not names:
        prefs.create_profile(app_dir, "Default")
        prefs.set_last_profile(app_dir, "Default")
        return prefs.ensure_profile_layout(os.path.join(profiles_d, "Default"))
    root = QWidget()
    root.setWindowTitle(app_version.APP_NAME)
    show_profiles_dialog(root, app_dir)
    last = prefs.get_last_profile(app_dir)
    if not last and names:
        prefs.set_last_profile(app_dir, names[0])
        last = names[0]
    if not last:
        prefs.create_profile(app_dir, "Default")
        prefs.set_last_profile(app_dir, "Default")
        last = "Default"
    return prefs.ensure_profile_layout(os.path.join(profiles_d, last))


def _cleanup_webengine_cache(profile_dir, force=False):
    """Trim stale/oversized WebEngine GPU caches.

    ``old_GPUCache_*`` are rotated-out snapshots and are always safe to drop.
    The live ``GPUCache`` is only rebuilt when it has grown abnormally large
    (corrupt/oversized caches make startup and first paint stutter); deleting
    it on every launch would just force a slow shader recompile each time.
    """
    data_dir = app_paths.browser_data_path(profile_dir)
    for name in ("old_GPUCache_000", "old_GPUCache_001", "old_GPUCache_002"):
        path = os.path.join(data_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    gpu = os.path.join(data_dir, "GPUCache")
    if not os.path.isdir(gpu):
        return
    if force:
        shutil.rmtree(gpu, ignore_errors=True)
        return
    try:
        total = 0
        for root, _dirs, files in os.walk(gpu):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    except OSError:
        total = 0
    if total > 300 * 1024 * 1024:
        shutil.rmtree(gpu, ignore_errors=True)


def _register_bundled_personal_sites(profile_dir, app_dir):
    """Register the four chained web apps as Personal Hub → Sites quick links.

    Only the local (file://) copies are registered — the deployed/cloud versions
    are surfaced on the Project Hub page (each card has a “☁ online version”
    link) instead, so the Sites list stays one entry per app and never shows
    raw deployed URLs.
    """
    # Prune the cloud duplicates older builds auto-registered. Only URLs that
    # match the chain's remote entries are removed; user-added http(s) sites
    # are left untouched.
    remote_urls = {
        site.get("url", "").strip()
        for site in app_paths.chain_remote_sites(app_dir)
        if site.get("url")
    }
    remote_urls.discard("")
    legacy_markers = tuple(app_paths.LEGACY_BUNDLED_FOLDER_MARKERS or ())
    for site in list(prefs.get_personal_sites(profile_dir)):
        url = (site.get("url") or "").strip()
        if not url:
            continue
        if url in remote_urls:
            prefs.remove_personal_site(profile_dir, url)
            continue
        # Drop stale duplicates that point at legacy bundled folders (e.g. the
        # old "Cục Quản Lý - Bản Đầy Đủ 1" hub) so the Sites list keeps exactly
        # one entry per bundled app — the canonical folder resolved below.
        unquoted_url = unquote(url)
        if any(marker in unquoted_url for marker in legacy_markers):
            prefs.remove_personal_site(profile_dir, url)
    for site in app_paths.bundled_sites(app_dir):
        if site.get("url"):
            prefs.add_personal_site(profile_dir, site["url"], site["display"])


def main(app_dir=None):
    """Run the app. Pass ``app_dir`` when started from repo-root ``browser.py`` shim; else repo root is inferred."""
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if _force_software_rendering():
        extra_flags = (
            "--disable-gpu "
            "--disable-software-rasterizer "
            "--disable-gpu-shader-disk-cache "
            "--disable-gpu-program-cache "
            "--enable-features=WebRTCPipeWireCapturer "
            "--disable-blink-features=AutomationControlled"
        )
        if extra_flags not in chromium_flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (chromium_flags + " " + extra_flags).strip()
        QCoreApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
    else:
        # AutomationControlled can make some sites treat QtWebEngine as a bot; disabling reduces false blocks.
        extra_flags = "--enable-features=WebRTCPipeWireCapturer --disable-blink-features=AutomationControlled"
        if extra_flags not in chromium_flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (chromium_flags + " " + extra_flags).strip()

    proxy_flag = _saved_proxy_chromium_flag(app_dir)
    if proxy_flag:
        existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
        if proxy_flag not in existing:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + proxy_flag).strip()
    app = QApplication(sys.argv)
    app.setApplicationName(app_version.APP_NAME)
    app.setApplicationVersion(app_version.APP_VERSION)
    app.setOrganizationName(app_version.APP_NAME)
    font = app.font()
    font.setStyleStrategy(QFont.PreferAntialias)
    # Multi-family fallback: unicode glyph icons (☕ ⚙ ◈ ≣ …) fall back to
    # Segoe UI Symbol / Emoji per character instead of rendering as boxes.
    font.setFamilies(["Segoe UI", "Segoe UI Symbol", "Segoe UI Emoji", "Helvetica Neue", "Arial"])
    app.setFont(font)

    app_paths.data_root(app_dir)
    app_paths.ensure_frozen_web_support_mirrored(app_dir)
    app_paths.ensure_linklumina_user_layout(app_dir)
    app.setWindowIcon(QIcon(os.path.join(app_dir, "icon.png")))
    profile_dir = _get_profile_dir(app_dir)
    workspace_manager.ensure_dual_workspaces(profile_dir)
    _register_bundled_personal_sites(profile_dir, app_dir)
    _cleanup_webengine_cache(
        profile_dir,
        force=os.environ.get("LITEBROWSER_CLEAN_GPU_CACHE_ON_START", "").strip().lower() in ("1", "true", "yes"),
    )
    windows = [
        AppShell(
            profile_dir,
            app_dir=app_dir,
            window_slot="primary",
            browser_workspace_id=workspace_manager.PRIMARY_WORKSPACE_ID,
        ),
        AppShell(
            profile_dir,
            app_dir=app_dir,
            window_slot="secondary",
            browser_workspace_id=workspace_manager.SECONDARY_WORKSPACE_ID,
        ),
    ]
    for window in windows:
        window.show()
    android_bridge_service.start_from_prefs(profile_dir)
    app.aboutToQuit.connect(android_bridge_service.stop)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
