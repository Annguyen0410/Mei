"""GreasyMonkey-style URL matching for local user-script extensions.

Each ``.js`` file in the Extensions folder may carry an optional metadata
block in the standard userscript header format::

    // ==UserScript==
    // @name        My tweak
    // @match       https://example.com/*
    // @exclude     https://example.com/private/*
    // ==/UserScript==

When no ``@match`` line is present the script keeps its legacy behaviour of
running on every page. When ``@match`` is present it runs only on matching
URLs; ``@exclude`` wins over ``@match``.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_NAME_RE = re.compile(r"//\s*@(\S+)\s*(.*)$")


def _glob_to_regex(pattern: str) -> str:
    """Convert a GreasyMonkey ``*`` glob to an anchored regex."""
    return re.escape(pattern or "").replace(r"\*", ".*")


def parse_user_script_metadata(source: str) -> tuple[list[str], list[str], str]:
    """Return ``(matches, excludes, name)`` from a ``==UserScript==`` block."""
    matches: list[str] = []
    excludes: list[str] = []
    name = ""
    in_block = False
    for line in (source or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("// ==UserScript=="):
            in_block = True
            continue
        if stripped.startswith("// ==/UserScript=="):
            in_block = False
            continue
        if not in_block:
            continue
        match = _NAME_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "match":
            matches.append(value)
        elif key == "exclude":
            excludes.append(value)
        elif key == "name" and not name:
            name = value
    return matches, excludes, name


def _matches_host(host: str, pattern_host: str) -> bool:
    if pattern_host == "*":
        return True
    if pattern_host.startswith("*."):
        base = pattern_host[2:]
        return host == base or host.endswith("." + base)
    return host == pattern_host


def url_matches_pattern(url: str, pattern: str) -> bool:
    """Match a URL against a GreasyMonkey ``scheme://host/path`` glob pattern."""
    try:
        scheme, rest = pattern.split("://", 1)
    except ValueError:
        return False
    parsed = urlparse(url or "")
    url_scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if scheme != "*" and url_scheme and url_scheme != scheme.lower():
        return False
    if "/" in rest:
        pattern_host, pattern_path = rest.split("/", 1)
        pattern_path = "/" + pattern_path
    else:
        pattern_host, pattern_path = rest, "/*"
    if not _matches_host(host, pattern_host):
        return False
    return re.fullmatch(_glob_to_regex(pattern_path), path) is not None


def script_matches(url: str, matches: list[str], excludes: list[str]) -> bool:
    """True when a user script should run on ``url`` given its metadata."""
    if excludes and any(url_matches_pattern(url, pattern) for pattern in excludes):
        return False
    if not matches:
        return True
    return any(url_matches_pattern(url, pattern) for pattern in matches)
