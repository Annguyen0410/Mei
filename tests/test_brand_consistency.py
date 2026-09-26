"""One brand string: the app calls itself whatever ``core/product.py`` says.

The UI used to carry two names at once — the taskbar, the New Tab page and four
dialogs said "MeiBrowser" while the .exe, the installer, the data folder and the
update channel all said Mei.  ``app_version.APP_NAME`` is now the only source, so
a future rename cannot leave half the window titled something else.
"""
import os
import tempfile
import unittest

import litebrowser  # noqa: F401  activates the Qt compatibility shim
from litebrowser.browser import new_tab_page
from litebrowser.core import app_version, prefs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "litebrowser")
RETIRED_NAME = "MeiBrowser"


class TestOneBrandString(unittest.TestCase):
    def test_brand_is_the_product_name(self):
        self.assertEqual(app_version.APP_NAME, app_version.PRODUCT_NAME)
        self.assertTrue(app_version.APP_NAME.strip())

    def test_no_module_hard_codes_the_retired_name(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(PACKAGE):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8-sig") as handle:
                    if RETIRED_NAME in handle.read():
                        offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual(
            offenders,
            [],
            f"use app_version.APP_NAME instead of the literal {RETIRED_NAME}",
        )

    def test_new_tab_page_shows_the_brand(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            html = new_tab_page.build_new_tab_html(base_dir)
        self.assertIn(f"<title>{app_version.APP_NAME} Home</title>", html)
        self.assertNotIn("@BRAND@", html, "the brand token must be substituted")
        self.assertNotIn(RETIRED_NAME, html)

    def test_docs_call_the_app_by_the_same_name(self):
        # The guides named the app after the retired string while the window said
        # something else, which is how a user ends up searching the wrong name.
        offenders = []
        targets = ["README.md", "ARCHITECTURE.md", "RUN_AND_BUILD.md"]
        docs_dir = os.path.join(ROOT, "docs")
        targets += [os.path.join("docs", name) for name in sorted(os.listdir(docs_dir)) if name.endswith(".md")]
        for relative in targets:
            with open(os.path.join(ROOT, relative), encoding="utf-8-sig") as handle:
                if RETIRED_NAME in handle.read():
                    offenders.append(relative)
        self.assertEqual(offenders, [])

    def test_window_titles_read_the_brand(self):
        # The two windows and the shell title come from different modules; each
        # one has to interpolate APP_NAME rather than spell the brand out.
        for relative in (
            "ui/app_shell.py",
            "ui/ai_window.py",
            "ui/personal_window.py",
            "browser/tab_manager.py",
        ):
            with open(os.path.join(PACKAGE, relative), encoding="utf-8-sig") as handle:
                text = handle.read()
            titles = [line for line in text.splitlines() if "setWindowTitle" in line]
            self.assertTrue(titles, relative)
            for line in titles:
                self.assertIn("app_version.APP_NAME", line, f"{relative}: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
