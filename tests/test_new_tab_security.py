"""New-tab page hardening checks."""
import os
import tempfile
import unittest

from litebrowser.browser.new_tab_page import build_new_tab_html
from litebrowser.core import prefs


class TestNewTabSecurity(unittest.TestCase):
    def test_new_tab_filters_executable_bookmark_urls_and_adds_csp(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            prefs.save_bookmarks(
                base,
                [
                    {"title": "<img src=x onerror=alert(1)>", "url": "javascript:alert(1)"},
                    {"title": "Safe", "url": "https://example.com/path?q=1"},
                ],
            )

            html = build_new_tab_html(base)

        self.assertIn("Content-Security-Policy", html)
        self.assertIn("default-src", html)
        self.assertNotIn("href=\"javascript:", html.lower())
        self.assertNotIn("<img src=x", html)
        self.assertIn("https://example.com/path?q=1", html)


if __name__ == "__main__":
    unittest.main()
