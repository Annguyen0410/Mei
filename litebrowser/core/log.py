"""Application logging: one rotating file under the data root.

The app previously swallowed errors silently (`except Exception: pass` with no
trace). Logging goes to ``runtime_data/logs/mei.log`` (rotated, capped) so
nothing is lost on the console of a frozen exe, while development stays quiet.
Every call here is safe: if the log file cannot be created, the app still runs.
"""
import logging
import logging.handlers
import os

_HANDLER = None
_LOG_DIR = None


def _open_handler(logs_dir: str) -> logging.handlers.RotatingFileHandler:
    os.makedirs(logs_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(logs_dir, "mei.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.setLevel(logging.DEBUG)
    return handler


def configure(app_dir=None) -> None:
    """Point the file handler at ``app_dir``'s data root. Idempotent, never raises.

    Call again when the real profile/app dir becomes known; the handler is
    re-pointed instead of keeping the development default.
    """
    global _HANDLER, _LOG_DIR
    if _HANDLER is not None and app_dir in (None, _LOG_DIR):
        return
    try:
        from litebrowser.core import app_paths

        logs_dir = os.path.join(app_paths.data_root(app_dir), "logs")
        if _LOG_DIR == logs_dir:
            return
        if _HANDLER is not None:
            root = logging.getLogger("litebrowser")
            root.removeHandler(_HANDLER)
            try:
                _HANDLER.close()
            except Exception:  # noqa: BLE001  fail-safe: never raise from logging
                pass
        _HANDLER = _open_handler(logs_dir)
        _LOG_DIR = logs_dir
        root = logging.getLogger("litebrowser")
        root.setLevel(logging.DEBUG)
        root.addHandler(_HANDLER)
        root.propagate = False
    except Exception as exc:  # noqa: BLE001  logging must never take the app down
        logging.getLogger("litebrowser.log").debug("could not open log file: %s", exc)
        if _HANDLER is not None:
            try:
                _HANDLER.close()
            except Exception:  # noqa: BLE001  fail-safe: never raise from logging
                pass
            _HANDLER = None


def get_logger(name: str) -> logging.Logger:
    """Logger namespaced under ``litebrowser`` so all output lands in one file."""
    configure(None)
    if not name or name == "litebrowser":
        return logging.getLogger("litebrowser")
    return logging.getLogger(f"litebrowser.{name}")
