# Mei - Windows native title bar dark mode helper
import ctypes
import sys

from PyQt5.QtCore import QTimer


def _set_windows_dark_titlebar(hwnd: int, enabled: bool = True) -> bool:
    """Best-effort: enable Windows immersive dark title bar for this hwnd."""
    if not hwnd or not sys.platform.startswith("win"):
        return False
    try:
        # DWMWA_USE_IMMERSIVE_DARK_MODE:
        #  - 19 on older Win10 builds
        #  - 20 on Win10 1903+ / Win11
        value = ctypes.c_int(1 if enabled else 0)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):
            res = dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(int(hwnd)),
                ctypes.c_int(attr),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if res == 0:
                return True
    except Exception:
        return False
    return False


def apply_dark_titlebar(widget, enabled: bool = True) -> None:
    """
    Apply dark native title bar on Windows.
    Safe no-op on non-Windows or when unsupported.
    """
    def _apply():
        try:
            hwnd = int(widget.winId())
        except Exception:
            hwnd = 0
        _set_windows_dark_titlebar(hwnd, enabled=enabled)

    # Delay until the native window handle exists.
    QTimer.singleShot(0, _apply)

