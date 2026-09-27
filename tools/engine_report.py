"""Print the Qt/Chromium engine this interpreter would run the app on.

CI runs this on every build, so a green run records *which* Chromium it tested
instead of implying "the newest one"; by hand it answers "is this checkout on
the new engine or the fallback?" in one line:

    .venv/Scripts/python.exe tools/engine_report.py

Both bindings are probed, newest first, because the app runs on whichever is
installed (``litebrowser/qt_compat.py`` rewrites PyQt5 imports onto PyQt6 when
it is present). A binding that is missing is reported as such rather than
skipped, so the line tells the whole story.
"""
import importlib
import sys

BINDINGS = ("PyQt6", "PyQt5")


def engine_line(binding: str) -> str:
    """One line for ``binding``, or the reason it cannot answer."""
    try:
        core = importlib.import_module(binding + ".QtWebEngineCore")
        qt_core = importlib.import_module(binding + ".QtCore")
    except Exception as exc:  # noqa: BLE001 - an unavailable binding is a fact
        return f"engine: {binding} unavailable ({type(exc).__name__})"
    chromium = getattr(core, "qWebEngineChromiumVersion", None)
    version = chromium() if callable(chromium) else "unknown"
    return (
        f"engine: {binding} {getattr(qt_core, 'PYQT_VERSION_STR', '?')}"
        f" / Qt {getattr(qt_core, 'QT_VERSION_STR', '?')}"
        f" / Chromium {version}"
    )


def main() -> int:
    installed = 0
    for binding in BINDINGS:
        line = engine_line(binding)
        print(line, flush=True)
        if "unavailable" not in line:
            installed += 1
    if not installed:
        print("engine: no Qt binding installed — run pip install -e '.[qt6]'", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
