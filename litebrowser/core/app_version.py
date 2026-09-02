import os

APP_NAME = "Mei"
APP_VERSION = "6.5.0"

# Auto-update channel: the app fetches this JSON to know when a new build exists.
# Host the file `update.json` (see litebrowser-update/ beside the project) at this
# URL, e.g. by dragging the litebrowser-update folder onto Netlify. Env vars still
# override both values for forks / local testing.
UPDATE_METADATA_URL = os.environ.get(
    "LITEBROWSER_UPDATE_METADATA_URL",
    "https://graceful-kangaroo-4ebbee.netlify.app/litebrowser-update/update.json",
).strip()
RELEASES_PAGE_URL = os.environ.get("LITEBROWSER_RELEASES_PAGE_URL", "").strip()
