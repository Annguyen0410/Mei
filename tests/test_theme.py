"""Theme/QSS sanity: substitution must be complete and free of typos for every palette."""
import unittest

from litebrowser.ui import theme


class TestThemeIntegrity(unittest.TestCase):
    MODES = ("cafe-night", "cafe-day", "ocean-night", "sand-day", "minimal", "minimal-night")

    def test_all_modes_render_without_leftover_placeholders(self):
        for mode in self.MODES:
            for qss in (
                theme.main_qss(mode),
                theme.dialog_qss(mode),
                theme.collapse_btn_qss(mode),
            ):
                with self.subTest(mode=mode):
                    self.assertNotIn("%(", qss)
                    self.assertNotIn("));" + ")", qss)  # double-close typo guard

    def test_palette_keys_present(self):
        p = theme._palette("cafe-night")
        for key in (
            "MAIN_BG", "MAIN_BG_ALT", "SIDEBAR_BG", "CARD_BG", "INPUT_BG",
            "TEXT", "TEXT_MUTED", "ACCENT", "ACCENT_HOVER", "BUTTON_BG",
            "BUTTON_HOVER", "MENU_BG", "MENU_ITEM_SEL", "BORDER_SOFT",
        ):
            with self.subTest(key=key):
                self.assertIn(key, p)
                self.assertTrue(p[key])

    def test_styles_cover_core_chrome(self):
        qss = theme.main_qss()
        for needle in ("#NavButton", "#CafeButton", "#UrlBar", "QPushButton", "#TabCounter", "QToolTip", "QSplitter"):
            with self.subTest(needle=needle):
                self.assertIn(needle, qss)


if __name__ == "__main__":
    unittest.main()
