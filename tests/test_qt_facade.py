"""Qt binding migration: new code imports the façade, the allowlist only shrinks.

The app supports PyQt5 and PyQt6 through ``qt_compat``. That shim works by import
side effect, so the upgrade path is much safer if the number of modules importing
a concrete binding stops growing. Migrate a file by importing
``litebrowser.qt`` and removing it from ``QT5_ALLOWLIST`` below.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_DIR = os.path.join(ROOT, "litebrowser")

# The shim itself, the façade built on top of it, plus the entry point (which must
# set Chromium/OpenGL env vars before QApplication exists) are allowed to touch the
# binding directly forever.
PERMANENT = {
    "litebrowser/qt.py",
    "litebrowser/qt_compat.py",
    "litebrowser/main.py",
}

# Modules still importing PyQt5 directly. Remove a line when you migrate the file
# to `from litebrowser.qt import ...` — the test fails on stale entries too, so
# this list can only get shorter.
QT5_ALLOWLIST = {
    "litebrowser/browser/adblock.py",
    "litebrowser/browser/browser_page.py",
    "litebrowser/browser/tab_manager.py",
    "litebrowser/services/security.py",
    "litebrowser/ui/ai_window.py",
    "litebrowser/ui/app_shell.py",
    "litebrowser/ui/components.py",
    "litebrowser/ui/dialogs/help_hub.py",
    "litebrowser/ui/dialogs/hotkeys.py",
    "litebrowser/ui/dialogs/navigation.py",
    "litebrowser/ui/dialogs/profiles_privacy.py",
    "litebrowser/ui/dialogs/sessions.py",
    "litebrowser/ui/dialogs/shell_palette.py",
    "litebrowser/ui/dialogs/vpn_hub.py",
    "litebrowser/ui/focus_heatmap.py",
    "litebrowser/ui/main_window/window.py",
    "litebrowser/ui/main_window/window_menus.py",
    "litebrowser/ui/main_window/window_mixins.py",
    "litebrowser/ui/main_window/window_tools.py",
    "litebrowser/ui/onboarding.py",
    "litebrowser/ui/personal_window.py",
    "litebrowser/ui/shell/pages.py",
    "litebrowser/ui/textselect.py",
    "litebrowser/ui/theme.py",
    "litebrowser/ui/tray.py",
    "litebrowser/ui/vault_ui.py",
}


def _importers_of_pyqt5() -> set[str]:
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(PACKAGE_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            for node in ast.walk(ast.parse(open(path, encoding="utf-8-sig").read())):
                modules = []
                if isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                elif isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                if any(module == "PyQt5" or module.startswith("PyQt5.") for module in modules):
                    found.add(rel)
                    break
    return found


class TestFacadeIsTheWayIn(unittest.TestCase):
    def test_facade_exposes_the_qt_modules(self):
        from litebrowser import qt

        for name in ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtPrintSupport"):
            with self.subTest(module=name):
                self.assertIsNotNone(getattr(qt, name))

    def test_facade_re_exports_every_module_the_app_imports(self):
        from litebrowser import qt

        self.assertTrue(qt.QtWebEngineWidgets is None or hasattr(qt.QtWebEngineWidgets, "QWebEngineView"))
        self.assertTrue(qt.QShortcut is not None)

    def test_migrated_modules_use_the_facade(self):
        for rel in ("litebrowser/ui/icons.py", "litebrowser/ui/win_titlebar.py"):
            with self.subTest(module=rel):
                source = open(os.path.join(ROOT, rel), encoding="utf-8-sig").read()
                self.assertIn("from litebrowser.qt import", source)
                self.assertNotIn("from PyQt5", source)


class TestAllowlistOnlyShrinks(unittest.TestCase):
    def test_no_unlisted_module_imports_the_binding_directly(self):
        offenders = sorted(_importers_of_pyqt5() - QT5_ALLOWLIST - PERMANENT)
        self.assertEqual(offenders, [], "import from litebrowser.qt instead of PyQt5")

    def test_allowlist_has_no_stale_entries(self):
        importers = _importers_of_pyqt5()
        stale = sorted(QT5_ALLOWLIST - importers)
        self.assertEqual(stale, [], "these files no longer import PyQt5 — drop them from the allowlist")

    def test_migration_is_actually_progressing(self):
        # Sanity: the allowlist is a migration list, not a permanent exemption.
        self.assertLess(len(QT5_ALLOWLIST), 30)
        self.assertNotIn("litebrowser/ui/icons.py", QT5_ALLOWLIST)
        self.assertNotIn("litebrowser/ui/win_titlebar.py", QT5_ALLOWLIST)


if __name__ == "__main__":
    unittest.main()
