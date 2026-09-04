"""Static NameError guard for the mixin modules.

The 0.6.8 mixin extraction shipped files that referenced names their import
block never imported (app_paths, QApplication, ...). ast.parse does not catch
that; this test walks every bare Name usage and subtracts imports, locals,
comprehension/loop targets, args and builtins — anything left would raise
NameError the first time the code path runs at runtime."""
import ast
import builtins
import os
import unittest

MIXIN_FILES = (
    "litebrowser/ui/main_window/window_menus.py",
    "litebrowser/ui/main_window/window_tools.py",
    "litebrowser/ui/main_window/window_mixins.py",
)


class TestMixinNameResolution(unittest.TestCase):
    def _missing_names(self, path):
        src = open(path, encoding="utf-8-sig").read()
        tree = ast.parse(src)
        imported, used, assigned = set(), set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imported.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    imported.add(a.asname or a.name)
            elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                assigned.add(n.name)
            elif isinstance(n, ast.arg):
                assigned.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                assigned.add(n.name)
            elif isinstance(n, ast.Name):
                used.add(n.id)
            elif isinstance(n, (ast.For, ast.comprehension)):
                target = n.target if isinstance(n, ast.For) else n.target
                for x in ast.walk(target):
                    if isinstance(x, ast.Name):
                        assigned.add(x.id)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            assigned.add(x.id)
        builtins_ = set(dir(builtins))
        return sorted(used - assigned - imported - builtins_ - {"self"})

    def test_all_mixin_files_resolve_names(self):
        for rel in MIXIN_FILES:
            with self.subTest(file=rel):
                missing = self._missing_names(rel)
                self.assertEqual(missing, [], f"{rel} would raise NameError at runtime: {missing}")

    def test_files_exist(self):
        for rel in MIXIN_FILES:
            self.assertTrue(os.path.isfile(rel), rel)


if __name__ == "__main__":
    unittest.main()
