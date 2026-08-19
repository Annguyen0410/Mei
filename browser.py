# Mei — run from repository root (icon.png, runtime_data live here).
import os
import sys

from litebrowser.main import main

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _app_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        _app_dir = os.path.dirname(os.path.abspath(__file__))
    main(app_dir=_app_dir)
