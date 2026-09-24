"""No dead public API in the data/utility layers.

The review that produced this file found one module nothing imported
(``services/app_models.py``) and a set of public functions with no caller
anywhere. Anything kept deliberately is exercised by ``tests/test_reserved_api.py``
and listed in ``docs/CAPABILITIES.md``; everything else must be deleted, so this
gate stays at zero.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "litebrowser"

# Entry points that are invoked by the framework/launcher rather than by name.
ENTRY_POINTS = {"main", "start", "stop"}


def _sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, PACKAGE)):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                sources[path] = open(path, encoding="utf-8-sig").read()
    for name in ("browser.py",):  # repo-root launcher
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            sources[path] = open(path, encoding="utf-8-sig").read()
    tests_dir = os.path.join(ROOT, "tests")
    for name in sorted(os.listdir(tests_dir)):
        if name.endswith(".py"):
            path = os.path.join(tests_dir, name)
            sources[path] = open(path, encoding="utf-8-sig").read()
    return sources


def _reference_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in _sources().values():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                counts[node.id] = counts.get(node.id, 0) + 1
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                counts[node.attr] = counts.get(node.attr, 0) + 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                counts[node.value] = counts.get(node.value, 0) + 1
    return counts


class TestNoDeadPublicApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = _reference_counts()
        cls.dead: list[str] = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, PACKAGE)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                for node in ast.parse(open(path, encoding="utf-8-sig").read()).body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name.startswith("_") or node.name in ENTRY_POINTS:
                            continue
                        if cls.counts.get(node.name, 0) == 0:
                            cls.dead.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} {node.name}")

    def test_no_unreferenced_public_definitions(self):
        self.assertEqual(
            self.dead,
            [],
            "unreferenced public API — wire it up, cover it in test_reserved_api.py "
            "and list it in docs/CAPABILITIES.md, or delete it",
        )


class TestDeletedSurfaceStaysDeleted(unittest.TestCase):
    """The junk removed in this pass must not creep back."""

    def test_app_models_module_is_gone(self):
        self.assertFalse(os.path.isfile(os.path.join(ROOT, "litebrowser", "services", "app_models.py")))

    def test_dead_prefs_pair_is_gone(self):
        from litebrowser.core import prefs

        self.assertFalse(hasattr(prefs, "get_block_webrtc_leak"))
        self.assertFalse(hasattr(prefs, "set_block_webrtc_leak"))

    def test_shell_facade_does_not_re_export(self):
        from litebrowser.ui import shell

        for name in ("HistoryPage", "HomeDashboardPage", "LibraryPage", "SettingsPage"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(shell, name))

    def test_timestamp_helper_has_one_implementation(self):
        from litebrowser.ui import personal_window

        self.assertEqual(personal_window._format_ts(0), "-")
        self.assertEqual(personal_window._format_ts("not-a-time"), "-")


if __name__ == "__main__":
    unittest.main()
