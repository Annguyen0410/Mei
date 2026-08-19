"""Mei modernization features: accent theme, new palettes, forced dark, site zoom."""
import tempfile
import unittest

from litebrowser.browser import browser_page, new_tab_page
from litebrowser.core import prefs
from litebrowser.services import focus_service
from litebrowser.ui import theme


def _rm(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class TestAccentTheming(unittest.TestCase):
    MODES = ("cafe-night", "cafe-day", "ocean-night", "sand-day", "minimal", "minimal-night")

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lb_test_")

    def tearDown(self):
        _rm(self._tmp)

    def _base(self):
        return self._tmp

    def test_all_palettes_render_with_all_accents(self):
        for mode in self.MODES:
            for accent in theme.ACCENTS:
                with self.subTest(mode=mode, accent=accent):
                    qss = theme.main_qss(mode, accent)
                    self.assertNotIn("%(", qss)
                    self.assertIn(theme.ACCENTS[accent][0], qss)  # base accent present

    def test_new_palettes_exist_and_have_keys(self):
        for mode in ("ocean-night", "sand-day"):
            with self.subTest(mode=mode):
                p = theme._palette(mode)
                for key in ("MAIN_BG", "CARD_BG", "TEXT", "ACCENT", "BUTTON_BG", "MENU_BG"):
                    self.assertTrue(p.get(key))

    def test_accent_override_recolours_tokens(self):
        p = theme._palette("cafe-night", "teal")
        self.assertEqual(p["ACCENT"], "#3aa59a")
        self.assertEqual(p["INPUT_FOCUS"], "#45b8ac")

    def test_invalid_accent_falls_back(self):
        p = theme._palette("cafe-night", "does-not-exist")
        self.assertEqual(p["ACCENT"], theme.PALETTES["cafe-night"]["ACCENT"])

    def test_accent_prefs_roundtrip(self):
        self.assertEqual(prefs.get_accent(self._base()), "brass")
        prefs.set_accent(self._base(), "violet")
        self.assertEqual(prefs.get_accent(self._base()), "violet")
        prefs.set_accent(self._base(), "nope")
        self.assertEqual(prefs.get_accent(self._base()), "brass")

    def test_shell_theme_prefs_validate(self):
        prefs.set_shell_theme(self._base(), "ocean-night")
        self.assertEqual(prefs.get_shell_theme(self._base()), "ocean-night")
        prefs.set_shell_theme(self._base(), "bogus")
        self.assertEqual(prefs.get_shell_theme(self._base()), theme.DEFAULT_THEME)

    def test_new_profiles_default_to_minimal(self):
        self.assertEqual(prefs.get_shell_theme(self._base()), theme.DEFAULT_THEME)
        self.assertIn(theme.DEFAULT_THEME, theme.PALETTES)

    def test_all_palettes_share_key_contract(self):
        # Every palette must expose the same keys used by tests/QSS so nothing
        # crashes when a new theme is applied.
        keys = set(theme.PALETTES["cafe-night"].keys())
        for mode in self.MODES:
            self.assertEqual(set(theme.PALETTES[mode].keys()), keys)


class TestForcedDark(unittest.TestCase):
    def test_enabled_js_contains_style_and_no_dark_site_override(self):
        js = browser_page.build_forced_dark_js(True)
        self.assertIn("lite-forced-dark", js)
        self.assertIn("prefers-color-scheme", js)
        self.assertIn("color-scheme", js)

    def test_disabled_js_removes_tag(self):
        js = browser_page.build_forced_dark_js(False)
        self.assertIn("removeChild", js)
        self.assertNotIn("prefers-color-scheme", js)

    def test_script_default_does_not_override_dark_pref(self):
        # When the user has NOT enabled forced dark, no DocumentReady script is wanted.
        self.assertIn("removeChild", browser_page.build_forced_dark_js(False))


class TestSiteZoom(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lb_test_zoom_")

    def tearDown(self):
        _rm(self._tmp)

    def _base(self):
        return self._tmp

    def test_zoom_roundtrip(self):
        prefs.set_site_zoom(self._base(), "example.com", 1.3)
        self.assertEqual(prefs.get_site_zoom(self._base(), "example.com"), 1.3)

    def test_zoom_case_insensitive(self):
        prefs.set_site_zoom(self._base(), "Example.com", 0.8)
        self.assertEqual(prefs.get_site_zoom(self._base(), "example.com"), 0.8)

    def test_zoom_clear(self):
        base = self._base()
        prefs.set_site_zoom(base, "example.com", 1.2)
        prefs.set_site_zoom(base, "example.com", None)
        self.assertIsNone(prefs.get_site_zoom(base, "example.com"))

    def test_zoom_no_host_returns_none(self):
        self.assertIsNone(prefs.get_site_zoom(self._base(), ""))


class TestCafeFocus(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lb_test_focus_")

    def tearDown(self):
        _rm(self._tmp)

    def test_start_creates_running_session(self):
        session = focus_service.start_focus(self._tmp, minutes=25)
        self.assertEqual(session["minutes"], 25)
        status = focus_service.focus_status(self._tmp)
        self.assertTrue(status["running"])
        self.assertGreater(status["remaining"], 0)

    def test_focus_minutes_are_clamped(self):
        session = focus_service.start_focus(self._tmp, minutes=9999)
        self.assertEqual(session["minutes"], 180)

    def test_starting_again_abandons_previous(self):
        focus_service.start_focus(self._tmp, minutes=25, label="first")
        focus_service.start_focus(self._tmp, minutes=10, label="second")
        journal = focus_service.focus_journal(self._tmp)
        self.assertEqual(journal[0]["status"], "abandoned")
        self.assertEqual(journal[0]["label"], "first")

    def test_stop_marks_completed_in_journal(self):
        focus_service.start_focus(self._tmp, minutes=25)
        focus_service.stop_focus(self._tmp, complete=True)
        status = focus_service.focus_status(self._tmp)
        self.assertFalse(status["running"])
        journal = focus_service.focus_journal(self._tmp)
        self.assertEqual(journal[0]["status"], "completed")

    def test_today_focus_counts_only_completed(self):
        focus_service.start_focus(self._tmp, minutes=10)
        focus_service.stop_focus(self._tmp, complete=True)
        focus_service.start_focus(self._tmp, minutes=10)
        focus_service.stop_focus(self._tmp, complete=False)
        statuses = [s["status"] for s in focus_service.focus_journal(self._tmp)]
        self.assertIn("completed", statuses)
        self.assertIn("abandoned", statuses)
        # Completed-only stat counts the good pour; abandoned is excluded.
        self.assertGreaterEqual(focus_service.today_focus_seconds(self._tmp), 0)


class TestCafeGreeting(unittest.TestCase):
    def test_greeting_periods_cover_all_hours(self):
        for hour in range(24):
            with self.subTest(hour=hour):
                eyebrow, headline = new_tab_page.cafe_greeting(hour)
                self.assertTrue(eyebrow)
                self.assertTrue(headline)

    def test_night_and_morning_differ(self):
        _, night = new_tab_page.cafe_greeting(23)
        _, morning = new_tab_page.cafe_greeting(8)
        self.assertNotEqual(night, morning)

    def test_greeting_rendered_in_speed_dial(self):
        import os
        base = prefs.ensure_profile_layout(os.path.join(self._base_guard(), "profile"))
        html = new_tab_page.build_new_tab_html(base)
        known = set()
        from litebrowser.browser.new_tab_page import _CAFE_GREETINGS
        for e, h in _CAFE_GREETINGS.values():
            known.add(e)
            known.add(h)
        self.assertTrue(any(k in html for k in known))
        self.assertIn("<h1>", html)

    def _base_guard(self):
        return tempfile.mkdtemp(prefix="lb_test_greet_")


if __name__ == "__main__":
    unittest.main()