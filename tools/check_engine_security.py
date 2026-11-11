"""State the WebEngine security version CI is about to test and ship.

A green run on Chromium base 140 says nothing about how much of Qt's patch
stream is in the build: Qt ships 6.11.0 at 146 and 6.11.3 at 155, all on base
140. This prints the number and fails when the *runtime* is below
``engine_security.MIN_SECURITY_VERSION``, so the engine cannot get quieter over
time.

The version is read from Qt, not from ``importlib.metadata``: the pinned
``PyQt6-WebEngine==6.11.0`` wheel imports Qt 6.11.1, so the package label
under-reports the patch level.

    python tools/check_engine_security.py            # print + gate
    python tools/check_engine_security.py --report   # print only

Exit codes: 0 above the floor, 1 below or unknown. With ``--report`` the gate is
skipped, but a missing WebEngine is still 1, because then the check never ran.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

# Running this file directly puts tools/ on sys.path, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from litebrowser.core import engine_security  # noqa: E402

_BINDINGS = ("PyQt6", "PyQt5")
_RUNTIME_MODULES = {
    "PyQt6": "PyQt6.QtWebEngineCore",
    "PyQt5": "PyQt5.QtWebEngine",
}


def runtime_qtwebengine_version() -> str:
    """The Qt WebEngine runtime version, or ``""`` when WebEngine is absent.

    The WebEngine modules do not all expose a version string (PyQt6's
    ``QtWebEngineCore`` exposes none), so Qt's own version is the fallback: for
    a given release line the two are the same number, and it is the Qt patch
    stream — not the wheel label — that decides the security version.
    """
    for binding in _BINDINGS:
        try:
            module = importlib.import_module(_RUNTIME_MODULES[binding])
        except Exception:  # noqa: BLE001 - a binding that will not import is absent
            continue
        for attr in ("QTWEBENGINE_VERSION_STR", "QT_VERSION_STR"):
            value = str(getattr(module, attr, "") or "").strip()
            if value:
                return value
        try:
            qtcore = importlib.import_module(binding + ".QtCore")
        except Exception:  # noqa: BLE001
            continue
        value = str(getattr(qtcore, "QT_VERSION_STR", "") or "").strip()
        if value:
            return value
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report the shipped WebEngine security version.")
    parser.add_argument("--report", action="store_true", help="print the number without failing the build")
    parser.add_argument("--floor", type=int, default=engine_security.MIN_SECURITY_VERSION)
    args = parser.parse_args(argv)

    installed = runtime_qtwebengine_version()
    if not installed:
        print("engine-security: no Qt WebEngine runtime — the check did not run", flush=True)
        return 0 if args.report else 1

    known = engine_security.known_engine(installed)
    if known is None:
        print(
            "engine-security: QtWebEngine %s — Chromium base and security version UNKNOWN."
            % installed,
            flush=True,
        )
        print(
            "engine-security: add it to litebrowser/core/engine_security.py _KNOWN after reading"
            " Qt's Chromium-version table; an unknown engine does not meet the floor.",
            flush=True,
        )
        return 0 if args.report else 1

    chromium, security = known
    ok = engine_security.meets_floor(security, args.floor)
    print(
        "engine-security: QtWebEngine %s / Chromium %d / security version %d (floor %d) — %s"
        % (installed, chromium, security, args.floor, "ok" if ok else "BELOW FLOOR"),
        flush=True,
    )
    if not ok and not args.report:
        print(
            "engine-security: raise the WebEngine pin to a runtime that carries the floor, then"
            " update MIN_SECURITY_VERSION; do not lower the floor to make CI green.",
            flush=True,
        )
    return 0 if (ok or args.report) else 1


if __name__ == "__main__":
    sys.exit(main())
