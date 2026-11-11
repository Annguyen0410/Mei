"""The Chromium security version behind the pinned WebEngine, and the floor.

Two numbers matter for a browser, and only one of them is visible in a version
string:

* the **Chromium base** (140 for the whole Qt 6.11 WebEngine line), and
* the **security version** — how much of Qt's backported patch stream is in the
  build. Qt ships 6.11.0 with security version 146, 6.11.1 with 148, 6.11.2 with
  151 and 6.11.3 with 155, all on Chromium base 140.

PyQt wheels do not follow those patch numbers: PyPI publishes ``6.11.0`` for
this line and then jumps to ``6.140.0`` (and publishes no 6.11.1/6.11.2/6.11.3
at all), so "just bump the pin to 6.11.3" is not an installable instruction.
This module records what each *installable* pin is known to carry, so CI can
state the number out loud and fail when a build drops below a declared floor
instead of quietly shipping a stale patch stream.

Pure module: no Qt import, so it is testable on any interpreter.
"""
from __future__ import annotations

__all__ = [
    "CHROMIUM_BASE",
    "MIN_SECURITY_VERSION",
    "UNKNOWN",
    "known_engine",
    "security_version_for",
    "meets_floor",
]

UNKNOWN = None

#: Chromium major the whole Qt 6.11 WebEngine line is built on.
CHROMIUM_BASE = 140

#: Oldest security version this project is willing to ship.
#:
#: Qt 6.11.0 = 146, and no newer WebEngine patch release is installable from
#: PyPI for this line, so 146 is the floor Mei can actually meet today. Raising
#: this constant is the release decision: check the Qt table for the binding
#: that ships, then raise it — CI fails until the pin really carries it.
MIN_SECURITY_VERSION = 146

#: PyQt WebEngine version -> (Chromium base, security version).
#:
#: Only values that were read from Qt's published Chromium-version table are
#: listed. A version that is not here reports ``UNKNOWN`` rather than a guess.
_KNOWN: dict[str, tuple[int, int]] = {
    "6.11.0": (140, 146),
}


def known_engine(webengine_version: str) -> tuple[int, int] | None:
    """``(chromium_base, security_version)`` for a PyQt WebEngine version."""
    return _KNOWN.get(str(webengine_version or "").strip())


def security_version_for(webengine_version: str) -> int | None:
    """Security version for ``webengine_version``, or ``None`` when unknown."""
    entry = known_engine(webengine_version)
    return entry[1] if entry else UNKNOWN


def meets_floor(security_version: int | None, floor: int = MIN_SECURITY_VERSION) -> bool:
    """True when ``security_version`` is at least ``floor``.

    An unknown version does not meet the floor: "we could not tell" is not the
    same as "it is patched", and the point of the gate is to stop that being
    assumed.
    """
    if security_version is None:
        return False
    try:
        return int(security_version) >= int(floor)
    except (TypeError, ValueError):
        return False
