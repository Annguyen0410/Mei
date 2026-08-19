"""Tests for search-engine persistence and the engine-aware new-tab speed dial."""
import os
import tempfile
import unittest

from litebrowser.browser import new_tab_page
from litebrowser.core import prefs


class TestSearchEnginePrefs(unittest.TestCase):
    def test_defaults_to_google(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            self.assertEqual(prefs.get_search_engine(base), "Google")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            prefs.set_search_engine(base, "DuckDuckGo")
            self.assertEqual(prefs.get_search_engine(base), "DuckDuckGo")

    def test_invalid_engine_falls_back_to_google(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            prefs.set_search_engine(base, "NotARealEngine")
            self.assertEqual(prefs.get_search_engine(base), "Google")


class TestEngineAwareNewTab(unittest.TestCase):
    def test_form_routes_to_selected_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            html = new_tab_page.build_new_tab_html(base, search_engine="Startpage")
        self.assertIn('action="https://www.startpage.com/search"', html)

    def test_duckduckgo_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            html = new_tab_page.build_new_tab_html(base, search_engine="DuckDuckGo")
        self.assertIn('action="https://duckduckgo.com/"', html)

    def test_default_engine_form_is_google(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            html = new_tab_page.build_new_tab_html(base)
        self.assertIn('action="https://www.google.com/search"', html)

    def test_engine_routing_uses_persisted_pref(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            prefs.set_search_engine(base, "Bing")
            html = new_tab_page.build_new_tab_html(base, search_engine=prefs.get_search_engine(base))
        self.assertIn('action="https://www.bing.com/search"', html)


class TestNewTabSingleTileAndShelf(unittest.TestCase):
    def test_bookmark_tile_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            prefs.save_bookmarks(
                base,
                [{"title": "Example", "url": "https://example.com/sub?q=1"}],
            )
            html = new_tab_page.build_new_tab_html(base)
        self.assertIn("https://example.com/sub?q=1", html)
        self.assertIn("Example", html)

    def test_csp_still_hardened(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            html = new_tab_page.build_new_tab_html(base, search_engine="DuckDuckGo")
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("default-src", html)
        self.assertIn("form-action", html)


if __name__ == "__main__":
    unittest.main()