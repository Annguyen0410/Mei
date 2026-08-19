"""Small shared time helpers (single source of truth across UI modules)."""
import time


def format_ts(ts_value: int) -> str:
    """Format a unix timestamp as ``YYYY-MM-DD HH:MM``, or ``-`` when empty."""
    if not ts_value:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts_value)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "-"
