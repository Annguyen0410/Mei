"""Which local (``file://``) documents Mei is willing to render, and why.

Qt's ``LocalContentCanAccessRemoteUrls`` is a *profile* switch: it cannot be
scoped to one origin. Mei needs that switch on, because the bundled chain apps
(``LinkLumina``, ``Cục Quản Lý``, the hub, ...) are real ``file://`` pages that
call their deployed APIs — turning it off breaks the product rather than
hardening it.

The capability is therefore defended at the door instead of in the engine: a
``file://`` document outside the trusted roots is refused *before* it loads, so
no untrusted document ever runs with that switch in reach. Opening a downloaded
``.html`` by hand is still possible, but only after the user opts in
``allow_untrusted_local_files``; the default is closed.

Everything here is pure (no Qt, no network) so the decision can be tested
without a browser.
"""
from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

__all__ = [
    "ALLOW",
    "BLOCK",
    "is_local_url",
    "is_trusted_local_url",
    "navigation_decision",
    "local_path",
    "trusted_local_roots",
]

ALLOW = "allow"
BLOCK = "block"


def local_path(url: str) -> str:
    """Filesystem path behind a ``file://`` URL, or ``""`` for anything else.

    A remote-looking authority (``file://host/share``) yields ``""``: serving a
    network share as trusted local content is exactly the confusion this module
    exists to stop.
    """
    try:
        parts = urlsplit(url or "")
    except (ValueError, TypeError):
        return ""
    if (parts.scheme or "").lower() != "file":
        return ""
    authority = (parts.netloc or "").lower()
    if authority not in ("", "localhost"):
        return ""
    path = unquote(parts.path or "")
    if not path:
        return ""
    # "file:///C:/x" keeps a leading slash that Windows paths do not want.
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path


def is_local_url(url: str) -> bool:
    """True when ``url`` addresses a local file (any location)."""
    return bool(local_path(url))


def trusted_local_roots(app_dir: str | None = None, extra=()) -> tuple[str, ...]:
    """Normalised folders whose ``file://`` pages Mei ships or owns.

    ``extra`` lets a window add roots it owns (a user-picked archive folder);
    it is folded in here so the decision stays in one place.
    """
    from litebrowser.core import app_paths

    roots: list[str] = []
    for factory in (app_paths.web_support_root, app_paths.linklumina_archive_dir):
        try:
            root = factory(app_dir)  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - a missing root is simply not trusted
            root = ""
        if root:
            roots.append(root)
    for root in extra or ():
        if root:
            roots.append(str(root))
    result: list[str] = []
    seen: set[str] = set()
    for root in roots:
        try:
            norm = os.path.normcase(os.path.abspath(root))
        except (OSError, ValueError):
            continue
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return tuple(result)


def is_trusted_local_url(url: str, roots) -> bool:
    """True when ``url`` is a local file inside one of ``roots``.

    Comparison is per path component (``root + sep``), so a sibling folder whose
    name merely starts with a trusted folder's name cannot inherit its trust.
    """
    path = local_path(url)
    if not path:
        return False
    try:
        target = os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return False
    for root in roots or ():
        if not root:
            continue
        try:
            root_norm = os.path.normcase(os.path.abspath(str(root)))
        except (OSError, ValueError):
            continue
        if target == root_norm:
            return True
        if target.startswith(root_norm + os.sep):
            return True
    return False


def navigation_decision(url: str, roots, allow_untrusted: bool = False) -> str:
    """``ALLOW`` or ``BLOCK`` for a top-level navigation to ``url``.

    Non-local schemes are always allowed: http(s), ``about:`` and the rest are
    governed by the engine's own rules and are not what this gate is for.
    """
    if not is_local_url(url):
        return ALLOW
    if is_trusted_local_url(url, roots):
        return ALLOW
    return ALLOW if allow_untrusted else BLOCK
