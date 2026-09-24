"""App identity — historical import site, values now owned by ``core/product.py``.

Kept so the ~40 existing ``app_version.X`` call sites keep working while there is
exactly one place that defines the product id, version, release channel and asset
name.  Add new identity facts to ``product.py``, never here.
"""
from litebrowser.core.product import (
    APP_NAME,
    APP_VERSION,
    ASSET_NAME,
    DEFAULT_UPDATE_CHANNEL_URL,
    MIN_PACKAGE_BYTES,
    PRODUCT_ID,
    PRODUCT_NAME,
    RELEASES_PAGE_URL,
    UPDATE_CHANNEL_PATH,
    UPDATE_METADATA_URL,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ASSET_NAME",
    "DEFAULT_UPDATE_CHANNEL_URL",
    "MIN_PACKAGE_BYTES",
    "PRODUCT_ID",
    "PRODUCT_NAME",
    "RELEASES_PAGE_URL",
    "UPDATE_CHANNEL_PATH",
    "UPDATE_METADATA_URL",
]
