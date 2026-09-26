"""The build ships web_support without the dead legacy hub copy.

``build_exe.bat`` used to ``xcopy`` all of ``web_support`` into ``dist`` and then
``rmdir`` the ``Cục Quản Lý - Bản Đầy Đủ 1`` duplicate. cmd.exe decodes a UTF-8
batch file in the OEM code page, so that name never matched the folder on disk:
~600 MB / 29k files of dead payload were copied on *every* build and shipped next
to Mei.exe. These tests pin the Python mirror that replaced it — skip while
copying, prune what older builds left behind — and the fact that the batch file
is pure ASCII again so it cannot rot the same way.
"""
import os
import tempfile
import unittest

import litebrowser  # noqa: F401  activates the Qt compatibility shim
from litebrowser.core import app_paths

from tools import sync_web_support

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(ROOT, "build_exe.bat")
LEGACY = app_paths.LEGACY_BUNDLED_FOLDER_MARKERS[0]

QUIET = lambda *args, **kwargs: None  # noqa: E731 - log sink for the tests


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class TestDeadPayloadIsSkipped(unittest.TestCase):
    def test_skip_list_comes_from_the_app(self):
        self.assertEqual(
            tuple(sync_web_support.SKIP_DIRS),
            tuple(app_paths.LEGACY_BUNDLED_FOLDER_MARKERS),
        )

    def test_legacy_folder_is_never_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "web_support")
            dest = os.path.join(tmp, "dist", "web_support")
            _write(os.path.join(source, "Cục Quản Lý", "index.html"), "<html>")
            _write(os.path.join(source, LEGACY, "index.html"), "<html>")
            _write(os.path.join(source, LEGACY, "assets", "big.js"), "x" * 4096)

            files, total = sync_web_support.sync(source, dest, log=QUIET)

            self.assertEqual(files, 1)
            self.assertEqual(total, len("<html>"))
            self.assertTrue(os.path.isfile(os.path.join(dest, "Cục Quản Lý", "index.html")))
            self.assertFalse(os.path.exists(os.path.join(dest, LEGACY)))

    def test_stale_copy_already_in_dist_is_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "web_support")
            dest = os.path.join(tmp, "dist", "web_support")
            _write(os.path.join(source, "hub", "index.html"))
            _write(os.path.join(dest, LEGACY, "index.html"))
            _write(os.path.join(dest, "hub", "dev.log"))

            sync_web_support.sync(source, dest, log=QUIET)

            self.assertFalse(os.path.exists(os.path.join(dest, LEGACY)))
            self.assertFalse(os.path.isfile(os.path.join(dest, "hub", "dev.log")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "hub", "index.html")))

    def test_dev_logs_are_not_shipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "web_support")
            dest = os.path.join(tmp, "dist", "web_support")
            _write(os.path.join(source, "MAS - Mahoraga Adapt System", "index.html"), "<html>")
            _write(os.path.join(source, "MAS - Mahoraga Adapt System", "server_test.log"))

            files, _ = sync_web_support.sync(source, dest, log=QUIET)

            self.assertEqual(files, 1)
            self.assertFalse(
                os.path.exists(os.path.join(dest, "MAS - Mahoraga Adapt System", "server_test.log"))
            )

    def test_prune_reports_nothing_for_a_missing_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sync_web_support.prune(os.path.join(tmp, "nope"), log=QUIET), 0)


class TestCommandLine(unittest.TestCase):
    def test_explicit_paths_are_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "out")
            _write(os.path.join(source, "chain.json"), "{}")

            self.assertEqual(sync_web_support.main([source, dest]), 0)
            self.assertTrue(os.path.isfile(os.path.join(dest, "chain.json")))

    def test_missing_source_fails_instead_of_shipping_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sync_web_support.main([os.path.join(tmp, "missing")]), 1)


class TestBuildScriptDelegates(unittest.TestCase):
    def test_build_script_is_pure_ascii(self):
        # The bug itself: cmd.exe reads the batch file in the OEM code page, so a
        # non-ASCII byte in a path there can never match what is on disk.
        with open(BUILD_SCRIPT, "rb") as handle:
            data = handle.read()
        self.assertEqual([byte for byte in data if byte > 127], [])

    def test_build_script_calls_the_sync_tool(self):
        with open(BUILD_SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("tools\\sync_web_support.py", text)
        self.assertNotIn("xcopy", text)


if __name__ == "__main__":
    unittest.main()
