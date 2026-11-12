"""The Chromium security version behind the WebEngine runtime, and the floor.

Two numbers matter for a browser, and only one of them is visible in a version
string:

* the **Chromium base** (140 for the whole Qt 6.11 WebEngine line), and
* the **security version** — how much of Qt's backported patch stream is in the
  build.

Keys here are Qt WebEngine **runtime** versions, not PyPI package versions. The
runtime is read from Qt rather than from ``importlib.metadata`` because the
wheel label is a package version while the security version follows the Qt
patch stream that wheel actually imports.

The pinned ``PyQt6-WebEngine==6.11.0`` reports runtime ``6.11.0`` — both in this
project's venv (``QT_VERSION_STR``) and in CI's engine report — which is security
version 146, exactly the current floor. An earlier revision of this comment
claimed the wheel imported Qt 6.11.1 and therefore carried 148; that was never
what the runtime reported, so it was corrected here rather than left to make a
future upgrade plan look one patch stream rosier than it is.

Qt ships 6.11.0 at 146, 6.11.1 at 148, 6.11.2 at 151 and 6.11.3 at 155, all on
Chromium base 140. PyPI publishes no 6.11.1/6.11.2/6.11.3 *wheels*, so "bump the
pin to 6.11.3" is not an installable instruction; a version missing from this
table reports ``UNKNOWN`` instead of a guess.

Pure module: no Qt import, so it is testable on any interpreter.
"""
from __future__ import annotations

__all__ = [
    "CHROMIUM_BASE",
    "MIN_SECURITY_VERSION",
    "UNKNOWN",
    "known_engine",
    "meets_floor",
    "security_version_for",
]

UNKNOWN = None

#: Chromium major the whole Qt 6.11 WebEngine line is built on.
CHROMIUM_BASE = 140

#: Oldest security version this project is willing to ship.
#:
#: Qt 6.11.0 is the oldest runtime the pinned wheel can resolve to, so 146 is the
#: floor Mei can actually meet today. Raising this constant is the release
#: decision: check Qt's published table for the runtime that ships, then raise
#: it — CI fails until the runtime really carries it.
MIN_SECURITY_VERSION = 146

#: Qt WebEngine runtime version -> (Chromium base, security version).
#:
#: Only values read from Qt's published Chromium-version table are listed. A
#: version that is not here reports ``UNKNOWN`` rather than a guess.
_KNOWN: dict[str, tuple[int, int]] = {
    "6.11.0": (140, 146),
    "6.11.1": (140, 148),
    "6.11.2": (140, 151),
    "6.11.3": (140, 155),
}


def known_engine(qt_webengine_version: str) -> tuple[int, int] | None:
    """``(chromium_base, security_version)`` for a Qt WebEngine runtime version."""
    return _KNOWN.get(str(qt_webengine_version or "").strip())


def security_version_for(qt_webengine_version: str) -> int | None:
    """Security version for the runtime, or ``None`` when it is not known."""
    entry = known_engine(qt_webengine_version)
    return entry[1] if entry else UNKNOWN


def meets_floor(security_version: int | None, floor: int | None = None) -> bool:
    """True when ``security_version`` is at least ``floor``.

    ``floor`` defaults to :data:`MIN_SECURITY_VERSION`, read at call time rather
    than bound as a default argument: a caller that raises the constant (and the
    diagnostics page, which quotes it back to the user) must see the same number
    the check just used.

    An unknown version does not meet the floor: "we could not tell" is not the
    same as "it is patched", and the point of the gate is to stop that being
    assumed.
    """
    if floor is None:
        floor = MIN_SECURITY_VERSION
    if security_version is None:
        return False
    try:
        return int(security_version) >= int(floor)
    except (TypeError, ValueError):
        return False
