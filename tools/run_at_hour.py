"""Run the clock-sensitive tests at a frozen hour.

Auto day/night resolves from ``time.localtime()``, so a test that leaves it on
while asserting a palette passes on whichever runner happens to be in the right
half of the day. That has now bitten this repo twice: the pour-by-night default
and the accent assertions in ``tests/test_theme_follows_shell.py`` (green at
23:xx here, red at 06:2x UTC on CI).

Freeze the hour and both halves are checkable from one machine::

    python tools/run_at_hour.py 10 tests/test_theme_follows_shell.py
    python tools/run_at_hour.py 22 tests/test_theme_follows_shell.py

With no paths it runs the whole suite, which is the honest version but slow;
CI runs the modules that read the clock instead.
"""

from __future__ import annotations

import sys
import time

import pytest

#: Modules that resolve auto day/night from the wall clock. Keep this list next
#: to the code it guards, so adding an assertion about a palette means adding the
#: file here too.
CLOCK_SENSITIVE = (
    "tests/test_theme_follows_shell.py",
    "tests/test_week_chart_days.py",
    "tests/test_scheduler_edges.py",
)


def freeze(hour: int) -> None:
    """Pin ``time.localtime`` to ``hour:00``, keeping the date."""
    real = time.localtime

    def localtime(secs=None):
        parts = real(secs)
        return time.struct_time(
            (parts.tm_year, parts.tm_mon, parts.tm_mday, hour, 0, 0, parts.tm_wday, parts.tm_yday, parts.tm_isdst)
        )

    time.localtime = localtime


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    hour = int(args.pop(0))
    paths = args or list(CLOCK_SENSITIVE)
    freeze(hour)
    print(f"frozen clock: local hour = {hour}")
    return pytest.main(["-p", "no:cacheprovider", "--no-header", "-q", *paths])


if __name__ == "__main__":
    raise SystemExit(main())
