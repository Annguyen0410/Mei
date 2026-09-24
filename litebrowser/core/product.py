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
APP_VERSION = "0.6.10.0"

# Release channel owned by this product. The web app (LinkLumina) publishes to
# .../litebrowser-update/update.json — deliberately a different path so the two
# products can no longer overwrite each other's releases.
UPDATE_CHANNEL_PATH = "mei-update/update.json"
DEFAULT_UPDATE_CHANNEL_URL = "https://graceful-kangaroo-4ebbee.netlify.app/" + UPDATE_CHANNEL_PATH

# Only this asset name may be installed by the self-updater.
ASSET_NAME = "Mei.exe"

# Minimum plausible size of a real build, so an HTML error page saved to disk can
# never be written over the running executable.
MIN_PACKAGE_BYTES = 1_000_000

UPDATE_METADATA_URL = os.environ.get("LITEBROWSER_UPDATE_METADATA_URL", DEFAULT_UPDATE_CHANNEL_URL).strip()
RELEASES_PAGE_URL = os.environ.get("LITEBROWSER_RELEASES_PAGE_URL", "").strip()

__all__ = [
    "PRODUCT_ID",
    "PRODUCT_NAME",
    "APP_NAME",
    "APP_VERSION",
    "ASSET_NAME",
    "MIN_PACKAGE_BYTES",
    "UPDATE_CHANNEL_PATH",
    "DEFAULT_UPDATE_CHANNEL_URL",
    "UPDATE_METADATA_URL",
    "RELEASES_PAGE_URL",
]
