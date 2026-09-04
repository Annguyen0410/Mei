"""Offscreen smoke: construct SearchWindow + AppShell to catch runtime errors
that unit tests miss (they never build the GUI)."""
import faulthandler
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --no-sandbox --disable-gpu-sandbox --disable-software-rasterizer"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
faulthandler.enable()
sys.stdout.reconfigure(line_buffering=True)

import litebrowser.ui.main_window.window as _w  # WebEngine before QApplication

print("import ok", flush=True)
from PyQt5.QtWidgets import QApplication

app = QApplication([])
print("app ok", flush=True)

from litebrowser.ui.main_window.window import SearchWindow

win = SearchWindow(embedded=True)
print("SearchWindow constructed", flush=True)
print("  browsers:", len(win.browsers), flush=True)
print("  tab_list rows:", win.tab_list.count(), flush=True)
print("  has panel_dock:", hasattr(win, "panel_dock"), flush=True)
print("  has split_dock:", hasattr(win, "split_dock"), flush=True)
print("  has dock_rail:", hasattr(win, "dock_rail"), flush=True)
print("  has link_preview:", hasattr(win, "link_preview"), flush=True)
print("  has load_progress:", hasattr(win, "load_progress"), flush=True)

# Exercise menu builders (they were the crash sites)
try:
    win._build_options_menu()
    print("options menu ok", flush=True)
except Exception as exc:
    print("options menu FAIL:", exc, flush=True)
try:
    win._build_page_menu()
    print("page menu ok", flush=True)
except Exception as exc:
    print("page menu FAIL:", exc, flush=True)

# Exercise the VPN hub + leak test construction (no network)
try:
    from litebrowser.ui.dialogs import vpn_hub
    print("vpn_hub import ok", flush=True)
except Exception as exc:
    print("vpn_hub FAIL:", exc, flush=True)

# Exercise personal window
try:
    from litebrowser.ui.personal_window import PersonalWindow
    pw = PersonalWindow(win.base_dir, embedded=True)
    print("PersonalWindow ok; review page present:", hasattr(pw, "review_card"), flush=True)
except Exception as exc:
    print("PersonalWindow FAIL:", exc, flush=True)

# Exercise AI window
try:
    from litebrowser.ui.ai_window import AIWindow
    aw = AIWindow(win.base_dir, embedded=True)
    print("AIWindow ok; provider badge:", hasattr(aw, "lbl_provider"), flush=True)
except Exception as exc:
    print("AIWindow FAIL:", exc, flush=True)

print("SMOKE DONE", flush=True)
