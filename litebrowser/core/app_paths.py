import json
import os
import shutil
import sys
from pathlib import Path

# On-disk data folder name. The app is branded "Mei" but older builds stored
# data under "LiteBrowser"; data_root() migrates the old folder over once so no
# profiles, sites, notes or settings are orphaned after the rename.
APP_NAME = "Mei"
LEGACY_DATA_FOLDER_NAME = "LiteBrowser"
APP_SCHEMA_VERSION = 2

CUC_QUAN_LY_DISPLAY_NAME = "C\u1ee5c Qu\u1ea3n L\u00fd"
# Canonical folder for the Cục Quản Lý hub. Older builds used the "Bản Đầy Đủ 1"
# folder; the new hub lives in plain "Cục Quản Lý" (with chain.json / MiroFish /
# worldmonitor), so legacy folder names below are ONLY used to prune stale entries.
CUC_QUAN_LY_SUPPORT_DIR = "Cục Quản Lý"
CUC_QUAN_LY_LEGACY_DIR = "Cục Quản Lý - Bản Đầy Đủ 1"

# Folder names older builds registered as the Cục Quản Lý bundled site. Any
# personal-site URL pointing into these is a stale duplicate of the canonical
# "Cục Quản Lý" folder and gets pruned at startup (main._register_bundled_personal_sites).
LEGACY_BUNDLED_FOLDER_MARKERS = (
    "Cục Quản Lý - Bản Đầy Đủ 1",
    "Cuc Quan Ly - Ban Day Du 1",
)

# The "project chain": four sibling web apps linked into the browser. Each entry
# maps a stable ASCII key to (a) a human title and (b) the folder names the app
# may live under — first the bundled web_support alias, then the live source folder.
BUNDLED_SITES = (
    {
        "key": "linklumina",
        "display": "LinkLumina",
        "subtitle": "Visual bookmark manager",
        "glyph": "🔖",
        "folders": ("link", "linklumina"),
    },
    {
        "key": "cucquanly",
        "display": "Cục Quản Lý",
        "subtitle": "Management center hub",
        "glyph": "📋",
        # Only the canonical folders are searched now; the legacy "Bản Đầy Đủ 1"
        # copies are intentionally NOT candidates so the Sites list can never
        # resolve to (or re-register) the old duplicated hub again.
        "folders": ("cucquanly", "Cục Quản Lý"),
    },
    {
        "key": "mas",
        "display": "MAS — Mahoraga Adapt System",
        "subtitle": "Adaptation trainer",
        "glyph": "🔄",
        "folders": ("mas", "MAS - Mahoraga Adapt System"),
    },
    {
        "key": "worldleaderboard",
        "display": "World Leaderboard",
        "subtitle": "Global rank calculator",
        "glyph": "🏆",
        "folders": ("worldleaderboard", "World Leaderboard"),
    },
)

# Deployed (remote) URLs come ONLY from chain.json — there are deliberately no
# hardcoded fallbacks here. Before anything is deployed, remote values are empty
# ("") and the chain runs fully local; after deploying, fill the real URLs in
# chain.json and they light up everywhere (hub “☁ online version” links, etc.).
REMOTE_SITE_FALLBACKS: dict[str, str] = {}
PROJECT_HUB_REMOTE = ""
CHAIN_JSON_NAME = "chain.json"


def project_root() -> str:
    # PyInstaller onefile: __file__ lives under _MEIPASS — do not use that as "repo root".
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # litebrowser/core/app_paths.py -> repository root (parent of litebrowser package)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def app_runtime_dir(app_dir: str | None = None) -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return app_dir or project_root()


def data_root(app_dir: str | None = None) -> str:
    env_value = os.environ.get("LITEBROWSER_DATA_DIR", "").strip()
    if env_value:
        root = env_value
    elif getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = local_app_data or os.path.expanduser("~")
        root = os.path.join(base, APP_NAME, "runtime_data")
        _migrate_legacy_data_folder(base, root)
    else:
        root = os.path.join(app_runtime_dir(app_dir), "runtime_data")
    os.makedirs(root, exist_ok=True)
    return root


def _migrate_legacy_data_folder(base: str, new_root: str) -> None:
    """One-time rename of the pre-rename data folder (%LOCALAPPDATA%\LiteBrowser).

    Older builds stored everything under "LiteBrowser"; after the rebrand to
    Mei the app would otherwise start with an empty profile. If the new Mei
    folder does not exist yet, move the legacy folder over so all profiles,
    sites, notes and settings survive the rename.
    """
    if os.path.isdir(new_root):
        return
    legacy = os.path.join(base, LEGACY_DATA_FOLDER_NAME, "runtime_data")
    if not os.path.isdir(legacy):
        return
    try:
        parent = os.path.dirname(new_root)
        os.makedirs(parent, exist_ok=True)
        shutil.move(legacy, new_root)
    except OSError:
        pass


def profiles_root(app_dir: str | None = None) -> str:
    path = os.path.join(data_root(app_dir), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


def last_profile_path(app_dir: str | None = None) -> str:
    return os.path.join(data_root(app_dir), "last_profile.txt")


def browser_data_path(base_dir: str) -> str:
    path = os.path.join(base_dir, "BrowserData")
    os.makedirs(path, exist_ok=True)
    return path


def downloads_dir(base_dir: str) -> str:
    path = os.path.join(base_dir, "Downloads")
    os.makedirs(path, exist_ok=True)
    return path


def web_support_root(app_dir: str | None = None) -> str:
    """Root folder containing support site folders (each with index.html)."""
    env = os.environ.get("LITEBROWSER_WEB_SUPPORT_DIR", "").strip()
    if env and os.path.isdir(env):
        return env
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = os.path.join(meipass, "web_support")
            if os.path.isdir(bundled):
                return bundled
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "web_support")
    return os.path.join(project_root(), "web_support")


def cuc_quan_ly_support_dir_candidates() -> tuple[str, ...]:
    # Only the canonical live "Cục Quản Lý" hub (and its ASCII web_support alias).
    # Legacy "Bản Đầy Đủ 1" folders are intentionally not searched anymore.
    return (
        "Cục Quản Lý",
        "cucquanly",
    )


def _dev_sibling_roots(app_dir: str | None = None) -> list[str]:
    """Live source folders next to (or one level above) the repository root.

    In a dev checkout the four chained apps live as siblings of the browser repo
    (e.g. D:/Code folder/<app>), so we can resolve the live copy instead of the
    bundled web_support snapshot. Harmless no-ops when running a packaged EXE.
    """
    roots: list[str] = []
    repo = project_root()
    for base in (os.path.dirname(repo), os.path.dirname(os.path.dirname(repo))):
        if base and os.path.isdir(base):
            roots.append(base)
    return roots


def _bundled_site_search_roots(app_dir: str | None = None) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if not path:
            return
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            return
        seen.add(norm)
        roots.append(path)

    # Priority order (highest first):
    #   1. explicit env var override
    #   2. live source folders next to the dev checkout (keeps the chain live)
    #   3. web_support folder shipped next to Mei.exe (current layout)
    #   4. the EXE directory itself (in case someone ran from repo root)
    #   5. legacy copy in %LOCALAPPDATA% (older EXE builds extracted there)
    #   6. source tree fallbacks (dev runs)
    env_ws = os.environ.get("LITEBROWSER_WEB_SUPPORT_DIR", "").strip()
    if env_ws:
        add(env_ws)
    for base in _dev_sibling_roots(app_dir):
        add(base)
    exe_dir = app_runtime_dir(app_dir)
    add(os.path.join(exe_dir, "web_support"))
    add(exe_dir)
    if getattr(sys, "frozen", False):
        add(os.path.join(data_root(app_dir), "web_support"))
    add(project_root())
    add(os.path.join(project_root(), "web_support"))
    add(web_support_root(app_dir))
    return roots


def bundled_site_index_path(key: str, app_dir: str | None = None) -> str:
    """Absolute path to a bundled site's index.html ('' when not found)."""
    spec = next((item for item in BUNDLED_SITES if item["key"] == key), None)
    if not spec:
        return ""
    for root in _bundled_site_search_roots(app_dir):
        for folder_name in spec["folders"]:
            candidate = os.path.join(root, folder_name)
            if os.path.isfile(os.path.join(candidate, "index.html")):
                return os.path.join(candidate, "index.html")
    return ""


def bundled_site_url(key: str, app_dir: str | None = None) -> str:
    path = bundled_site_index_path(key, app_dir)
    if not path:
        return ""
    return Path(path).resolve().as_uri()


def chain_manifest_path(app_dir: str | None = None) -> str:
    """Absolute path to the shared chain.json manifest ('' when missing)."""
    for root in _bundled_site_search_roots(app_dir):
        candidate = os.path.join(root, CHAIN_JSON_NAME)
        if os.path.isfile(candidate):
            return candidate
    return ""


def chain_manifest(app_dir: str | None = None) -> dict:
    """Parsed chain.json — the single source of truth linking all five apps."""
    path = chain_manifest_path(app_dir)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("apps"), list):
                return data
        except (OSError, ValueError):
            pass
    return {}


def _chain_remote_by_id(app_dir: str | None = None) -> dict[str, str]:
    manifest = chain_manifest(app_dir)
    mapping: dict[str, str] = {}
    for app in manifest.get("apps", []):
        if isinstance(app, dict) and app.get("id") and app.get("remote"):
            mapping[str(app["id"])] = str(app["remote"])
    return mapping


def bundled_sites(app_dir: str | None = None) -> list[dict]:
    """The four chained sites with resolved file:// URLs plus remote (deployed)
    URLs from chain.json. ``url`` == '' when the local copy is missing."""
    remote_by_id = _chain_remote_by_id(app_dir)
    result: list[dict] = []
    for spec in BUNDLED_SITES:
        item = dict(spec)
        item["url"] = bundled_site_url(spec["key"], app_dir)
        item["remote"] = remote_by_id.get(spec["key"]) or REMOTE_SITE_FALLBACKS.get(spec["key"], "")
        result.append(item)
    return result


def chain_remote_sites(app_dir: str | None = None) -> list[dict]:
    """Deployed (cloud) versions of the four apps plus the hub, from chain.json.
    Each item has url = remote URL so it can be registered as a Personal site."""
    remote_by_id = _chain_remote_by_id(app_dir)
    result: list[dict] = []
    for spec in BUNDLED_SITES:
        remote = remote_by_id.get(spec["key"]) or REMOTE_SITE_FALLBACKS.get(spec["key"], "")
        if not remote:
            continue
        result.append({
            "key": spec["key"],
            "display": spec["display"],
            "subtitle": spec.get("subtitle", ""),
            "glyph": spec.get("glyph", "▦"),
            "url": remote,
            "remote": remote,
        })
    hub_remote = project_hub_remote_url(app_dir)
    if hub_remote:
        result.append({
            "key": "hub",
            "display": "Project Hub",
            "subtitle": "Project chain portal",
            "glyph": "☰",
            "url": hub_remote,
            "remote": hub_remote,
        })
    return result


PROJECT_HUB_DIR = "hub"


def project_hub_index_path(app_dir: str | None = None) -> str:
    """Absolute path to the shared Project Hub landing page ('' when missing)."""
    for root in _bundled_site_search_roots(app_dir):
        candidate = os.path.join(root, PROJECT_HUB_DIR)
        if os.path.isfile(os.path.join(candidate, "index.html")):
            return os.path.join(candidate, "index.html")
    return ""


def project_hub_url(app_dir: str | None = None) -> str:
    path = project_hub_index_path(app_dir)
    if not path:
        return ""
    return Path(path).resolve().as_uri()


def project_hub_remote_url(app_dir: str | None = None) -> str:
    """Remote (deployed) URL of the Project Hub, from chain.json ('' if unset)."""
    return _chain_remote_by_id(app_dir).get("hub", "") or ""


def ensure_frozen_web_support_mirrored(app_dir: str | None = None) -> None:
    """Copy bundled web_support from _MEIPASS to the data folder's web_support once (EXE)."""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    src = os.path.join(meipass, "web_support")
    if not os.path.isdir(src):
        return
    dest = os.path.join(data_root(app_dir), "web_support")
    if os.path.isfile(os.path.join(dest, "cucquanly", "index.html")):
        return
    if os.path.isfile(os.path.join(dest, CUC_QUAN_LY_SUPPORT_DIR, "index.html")):
        return
    try:
        shutil.copytree(src, dest, dirs_exist_ok=True)
    except Exception:
        pass


def cuc_quan_ly_support_dir_path(app_dir: str | None = None) -> str:
    for root in _bundled_site_search_roots(app_dir):
        for folder_name in cuc_quan_ly_support_dir_candidates():
            candidate = os.path.join(root, folder_name)
            if os.path.isfile(os.path.join(candidate, "index.html")):
                return candidate
    return ""


def cuc_quan_ly_support_index_path(app_dir: str | None = None) -> str:
    """Absolute path to index.html if present, else ''."""
    support_dir = cuc_quan_ly_support_dir_path(app_dir)
    if not support_dir:
        return ""
    path = os.path.join(support_dir, "index.html")
    return path if os.path.isfile(path) else ""


def cuc_quan_ly_support_url(app_dir: str | None = None) -> str:
    path = cuc_quan_ly_support_index_path(app_dir)
    if not path:
        return ""
    return Path(path).resolve().as_uri()


def linklumina_archive_dir(app_dir: str | None = None) -> str:
    """
    Persistent folder OUTSIDE bundled web_support — survives EXE updates.
    Use for exports/backups from LinkLumina; IndexedDB still lives under profile BrowserData for file:// URLs.
    """
    root = os.path.join(data_root(app_dir), "LinkLumina")
    os.makedirs(root, exist_ok=True)
    return root


def ensure_linklumina_user_layout(app_dir: str | None = None) -> None:
    root = linklumina_archive_dir(app_dir)
    readme = os.path.join(root, "README_Mei.txt")
    if os.path.isfile(readme):
        return
    try:
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                "Mei — persistent LinkLumina folder\n"
                "========================================\n\n"
                "This folder lives inside runtime_data (e.g. %LOCALAPPDATA%\\Mei\\runtime_data\\LinkLumina), "
                "NOT inside the EXE installer — updating the app does not delete data stored here.\n\n"
                "LinkLumina data kept in the browser (IndexedDB / localStorage) is stored by Qt WebEngine under "
                "your profile (BrowserData). Keep the profile and the file path to link/index.html unchanged "
                "so the vault is not “lost” inside the app.\n\n"
                "Export JSON/XLSX backups from LinkLumina into this folder to keep a copy outside the browser.\n"
            )
    except OSError:
        pass
