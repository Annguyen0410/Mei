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

Three rules make that door hold:

* **every** ``file:`` URL is judged, including the ones this module cannot map
  to a local path. ``file://fileserver/share/x.html`` is a UNC share, not local
  content, and it is refused: it used to fall through as "not local, therefore
  allowed", which put a network document behind the same switch. A network
  authority is refused even when the user has opted into untrusted local files —
  that setting is about *where* a document came from, not about letting the
  browser open SMB connections.
* the comparison uses :func:`os.path.realpath`, so a symlink or a Windows
  directory junction whose *name* sits inside ``web_support`` but whose target
  is outside it does not inherit that folder's trust. ``abspath`` alone did.
* anything this module cannot decide is a refusal (see
  ``BrowserPage.acceptNavigationRequest``): the caller has to fail closed, since
  the failure mode of the switch being in reach is arbitrary local code with
  network access.

Everything here is pure (no Qt, no network) so the decision can be tested
without a browser.
"""
from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

__all__ = [
    "ALLOW",
    "BLOCK",
    "is_file_url",
    "is_local_url",
    "is_trusted_local_url",
    "navigation_decision",
    "local_path",
    "trusted_local_roots",
]

ALLOW = "allow"
BLOCK = "block"


def is_file_url(url: str) -> bool:
    """True for any ``file:`` URL, whether or not it names a local path."""
    try:
        parts = urlsplit(url or "")
    except (ValueError, TypeError):
        return False
    return (parts.scheme or "").lower() == "file"


def _authority_is_local(authority: str) -> bool:
    """``""``/``localhost`` and the RFC 8089 ``file://C:/x`` drive form."""
    if authority in ("", "localhost"):
        return True
    return len(authority) == 2 and authority[1] == ":" and authority[0].isalpha()


def local_path(url: str) -> str:
    """Filesystem path behind a ``file://`` URL, or ``""`` for anything else.

    ``""`` means "this is not a local filesystem path" — which includes a
    ``file:`` URL with a network authority (``file://host/share``) and a
    UNC-shaped path (``file:////host/share``). Callers that need to know the
    difference between "not local" and "local but untrusted" must ask
    :func:`is_file_url` as well; serving a network share as trusted local
    content is exactly the confusion this module exists to stop.
    """
    if not is_file_url(url):
        return ""
    parts = urlsplit(url or "")
    authority = (parts.netloc or "").lower()
    path = unquote(parts.path or "")
    if authority and not _authority_is_local(authority):
        return ""
    if authority and authority not in ("", "localhost"):
        # file://C:/Users/me -> C:/Users/me
        path = authority + path
    if not path:
        return ""
    # "//host/share" is a UNC path, not a local one — and so is the same path
    # written with backslashes ("/\\host\share"), which a URL can carry.
    if path.replace("\\", "/").startswith("//"):
        return ""
    # "file:///C:/x" keeps a leading slash that Windows paths do not want.
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path


def is_local_url(url: str) -> bool:
    """True when ``url`` addresses a local file (any location)."""
    return bool(local_path(url))


def _resolved(path: str) -> str:
    """Absolute, symlink/junction-free, case-folded form of ``path``.

    ``realpath`` is what resolves a Windows directory junction or a symlink to
    its target; ``abspath`` only normalises ``..`` and separators, so a name
    inside a trusted root could point anywhere.
    """
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


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
            norm = _resolved(root)
        except (OSError, ValueError):
            continue
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return tuple(result)


def is_trusted_local_url(url: str, roots) -> bool:
    """True when ``url`` resolves to a local file inside one of ``roots``.

    Both sides are resolved first, so a symlink or junction cannot borrow the
    trust of the folder it appears to sit in. Comparison is per path component
    (``root + sep``), so a sibling folder whose name merely starts with a trusted
    folder's name cannot inherit its trust either.
    """
    path = local_path(url)
    if not path:
        return False
    try:
        target = _resolved(path)
    except (OSError, ValueError):
        return False
    for root in roots or ():
        if not root:
            continue
        try:
            root_norm = _resolved(str(root))
        except (OSError, ValueError):
            continue
        prefix = root_norm if root_norm.endswith(os.sep) else root_norm + os.sep
        if target == root_norm or target.startswith(prefix):
            return True
    return False


def navigation_decision(url: str, roots, allow_untrusted: bool = False) -> str:
    """``ALLOW`` or ``BLOCK`` for navigating to ``url``.

    Non-``file:`` schemes are always allowed: http(s), ``about:`` and the rest
    are governed by the engine's own rules and are not what this gate is for.

    ``allow_untrusted`` is the user's explicit "I will open a downloaded page"
    setting. It only ever unlocks a *local* file outside the roots: a network
    authority is refused whatever the setting says, because the risk there is
    opening an SMB connection, not the provenance of the document.
    """
    if not is_file_url(url):
        return ALLOW
    if not is_local_url(url):
        return BLOCK
    if is_trusted_local_url(url, roots):
        return ALLOW
    return ALLOW if allow_untrusted else BLOCK
