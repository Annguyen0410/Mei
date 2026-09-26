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


class TestGeometryScale(unittest.TestCase):
    """One radius scale for the whole chrome.

    The UI had grown twelve distinct ad-hoc corner values (4px…20px); every
    surface that matters now resolves through these five tokens, so a control
    cannot invent a silhouette that matches nothing else on screen.
    """

    TOKENS = ("RADIUS_XS", "RADIUS_SM", "RADIUS", "RADIUS_LG", "RADIUS_PILL")

    def test_every_radius_token_is_defined(self):
        palette = theme._palette("cafe-night")
        for token in self.TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, palette)
                self.assertTrue(palette[token].endswith("px"))

    def test_the_scale_increases(self):
        palette = theme._palette("cafe-night")
        values = [int(palette[token].removesuffix("px")) for token in self.TOKENS[:-1]]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), len(values), "no two steps may share a value")

    def test_the_stylesheet_uses_the_scale(self):
        palette = theme._palette("cafe-night")
        qss = theme.main_qss("cafe-night")
        # Cards come from the card token, controls from the small one, pills from
        # the pill token - no bare numbers for the surfaces that carry the UI.
        self.assertIn("#SectionCard, #StatCard, #ActionTile, #StatTile, #InsightPanel { border-radius: %s; }" % palette["RADIUS"], qss)
        self.assertIn("QPushButton, #CafeButton, #TopIconButton { border-radius: %s; }" % palette["RADIUS_SM"], qss)
        self.assertIn("border-radius: %s;" % palette["RADIUS_PILL"], qss)

    def test_every_mode_resolves_the_scale(self):
        for mode in TestThemeIntegrity.MODES:
            qss = theme.main_qss(mode)
            with self.subTest(mode=mode):
                self.assertNotIn("%(RADIUS", qss)
                self.assertIn("border-radius: 14px;", qss)

    def test_keyboard_focus_is_visible_on_controls(self):
        qss = theme.main_qss()
        self.assertIn("QPushButton:focus", qss)
        self.assertIn("#TopIconButton:focus", qss)


if __name__ == "__main__":
    unittest.main()
