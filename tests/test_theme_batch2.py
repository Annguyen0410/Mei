"""Theme batch 2: weather and time of day.

The 2026 pass added four palettes — Rainy Day, Rainy Night, Sunrise, Autumn
Table. Key parity with the reference theme is enforced for *every* palette by
``test_modernization``; this file pins the two things that are specific to a
theme being *presentable*:

* it has a menu label that is not just its id (nobody picks "rain-night" from a
  menu — they pick "Rainy Night · late drizzle");
* auto day/night lands somewhere sensible, including when the user explicitly
  chose the night half of a pair.
"""
import os
import tempfile
import unittest
from unittest import mock

from litebrowser.core import prefs
from litebrowser.core import theme_data
from litebrowser.ui import theme

BATCH2 = ("rain-day", "rain-night", "sunrise-day", "autumn-day")


class _FakeClock:
    def __init__(self, hour: int):
        self.tm_hour = hour


class TestThemeBatch2(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def _auto_theme_at(self, hour: int, chosen: str) -> str:
        prefs.set_shell_theme(self.base, chosen)
        prefs.set_auto_theme(self.base, True)
        with mock.patch.object(prefs.time, "localtime", lambda: _FakeClock(hour)):
            return prefs.resolved_auto_theme(self.base)

    def test_every_new_theme_is_registered_and_labelled(self):
        for mode in BATCH2:
            self.assertIn(mode, theme.PALETTES, mode)
            label = theme.theme_display_name(mode)
            self.assertNotEqual(label, mode, f"{mode} needs a menu label, not its id")
            self.assertTrue(label.strip())

    def test_every_new_theme_resolves_to_a_real_palette(self):
        for mode in BATCH2:
            tokens = theme.palette_tokens(mode, "brass")
            for key in ("MAIN_BG", "TEXT", "ACCENT", "CARD_BG"):
                self.assertRegex(tokens[key], r"^#[0-9a-fA-F]{6}$", f"{mode}.{key}")
            self.assertEqual(set(theme.PALETTES[mode]), set(theme.PALETTES["cafe-night"]), mode)

    def test_the_rain_pair_swaps_with_the_hour(self):
        self.assertEqual(self._auto_theme_at(10, "rain-day"), "rain-day")
        self.assertEqual(self._auto_theme_at(22, "rain-day"), "rain-night", "a rainy day gets a rainy night")

    def test_choosing_the_night_half_keeps_it_at_night(self):
        self.assertEqual(self._auto_theme_at(22, "rain-night"), "rain-night")
        self.assertEqual(self._auto_theme_at(10, "rain-night"), "rain-day", "daylight still gets the day palette")

    def test_sunrise_is_light_and_autumn_pairs_with_a_night(self):
        self.assertFalse(theme_data.is_night_theme("sunrise-day"))
        self.assertFalse(theme_data.is_night_theme("autumn-day"))
        self.assertTrue(theme_data.is_night_theme("rain-night"))
        self.assertEqual(self._auto_theme_at(22, "sunrise-day"), "midnight-ember")
        self.assertEqual(self._auto_theme_at(22, "autumn-day"), "cafe-night")

    def test_the_picker_offers_more_than_sixteen_themes(self):
        self.assertGreaterEqual(len(theme.PALETTES), 20)
        self.assertEqual(len(theme.PALETTES), len(set(theme.PALETTES)))
        for mode in theme.PALETTES:
            self.assertIn(mode, theme_data.THEME_LABELS, f"{mode} has no label")


if __name__ == "__main__":
    unittest.main()
