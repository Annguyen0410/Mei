"""Product identity — the single source of truth for *which* product this is.

Three artefacts are produced from this repository: the desktop app, the release
channel JSON that the app polls, and the packaged installer.  They used to share
a version string, a Netlify path and a download link with the LinkLumina web app,
so the desktop build read LinkLumina's metadata (6.2.4), considered it newer than
Mei (0.6.9.0) and would happily replace ``Mei.exe`` with the other product's
binary.

Rules for future upgrades:

* every identity string lives here — no other module hard-codes the channel URL
  or the release asset name;
* an update channel declares ``"product": PRODUCT_ID``; anything else is refused
  rather than installed (see ``services/update_service.py``);
* the channel URL is Mei's own path, never the one the web app publishes to.
"""
import os

# Machine identity used in update metadata and download URLs.
PRODUCT_ID = "mei"
PRODUCT_NAME = "Mei"
APP_NAME = PRODUCT_NAME
APP_VERSION = "0.7.0.0"

# Release channel owned by this product. It used to point at a Netlify path
# (…/mei-update/update.json) that was never deployed — the only thing that host
# actually served was the LinkLumina web app's channel — so every installed Mei
# polled a 404 and could never upgrade itself. The channel is now the
# ``update.json`` asset of the newest GitHub Release, which resolves for as long
# as the repository lives and needs no server of its own.
RELEASES_REPO = "Annguyen0410/Mei"
UPDATE_CHANNEL_PATH = "releases/latest/download/update.json"
RELEASES_BASE_URL = "https://github.com/" + RELEASES_REPO + "/"
DEFAULT_UPDATE_CHANNEL_URL = RELEASES_BASE_URL + UPDATE_CHANNEL_PATH

# Only this asset name may be installed by the self-updater.
ASSET_NAME = "Mei.exe"

# Minimum plausible size of a real build, so an HTML error page saved to disk can
# never be written over the running executable.
MIN_PACKAGE_BYTES = 1_000_000

UPDATE_METADATA_URL = os.environ.get("LITEBROWSER_UPDATE_METADATA_URL", DEFAULT_UPDATE_CHANNEL_URL).strip()
# "Open release page" used to be an empty string, so the button could only tell
# the user that no release page was configured. It now opens this release line.
RELEASES_PAGE_URL = os.environ.get("LITEBROWSER_RELEASES_PAGE_URL", RELEASES_BASE_URL + "releases/latest").strip()

__all__ = [
    "PRODUCT_ID",
    "PRODUCT_NAME",
    "APP_NAME",
    "APP_VERSION",
    "ASSET_NAME",
    "MIN_PACKAGE_BYTES",
    "RELEASES_REPO",
    "RELEASES_BASE_URL",
    "UPDATE_CHANNEL_PATH",
    "DEFAULT_UPDATE_CHANNEL_URL",
    "UPDATE_METADATA_URL",
    "RELEASES_PAGE_URL",
]
