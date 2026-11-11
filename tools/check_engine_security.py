"""State the WebEngine security version CI is about to test and ship.

A green run on Chromium base 140 says nothing about how much of Qt's patch
stream is in the build: Qt ships 6.11.0 with security version 146 and 6.11.3
with 155, all on base 140. This prints the number and fails when the installed
pin is below ``engine_security.MIN_SECURITY_VERSION``, so the engine cannot get
quieter over time.

    python tools/check_engine_security.py            # print + gate
    python tools/check_engine_security.py --report   # print only

Exit codes: 0 above the floor, 1 below or unknown, 0 with --report unless the
package is missing entirely (then 1, because the check did not run).
"""
from __future__ import annotations

import argparse
import os
import sys

# Running this file directly puts tools/ on sys.path, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from litebrowser.core import engine_security  # noqa: E402


def installed_webengine_version() -> str:
    """Installed PyQt6-WebEngine version, or "" when it is not installed."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8
        return ""
    for name in ("PyQt6-WebEngine", "PyQt5-WebEngine"):
        try:
            return version(name)
        except PackageNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - a broken metadata file is "unknown"
            return ""
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report the pinned WebEngine security version.")
    parser.add_argument("--report", action="store_true", help="print the number without failing the build")
    parser.add_argument("--floor", type=int, default=engine_security.MIN_SECURITY_VERSION)
    args = parser.parse_args(argv)

    installed = installed_webengine_version()
    if not installed:
        print("engine-security: no PyQt WebEngine package installed — the check did not run", flush=True)
        return 0 if args.report else 1

    known = engine_security.known_engine(installed)
    if known is None:
        print(
            "engine-security: PyQt6-WebEngine %s — Chromium base and security version UNKNOWN."
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
        "engine-security: PyQt6-WebEngine %s / Chromium %d / security version %d (floor %d) — %s"
        % (installed, chromium, security, args.floor, "ok" if ok else "BELOW FLOOR"),
        flush=True,
    )
    if not ok and not args.report:
        print(
            "engine-security: raise the WebEngine pin to a build that carries the floor, then"
            " update MIN_SECURITY_VERSION; do not lower the floor to make CI green.",
            flush=True,
        )
    return 0 if (ok or args.report) else 1


if __name__ == "__main__":
    sys.exit(main())
