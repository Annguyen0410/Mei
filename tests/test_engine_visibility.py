"""The engine numbers Mei reports, sends, and shows.

Two places care about which Chromium is underneath, and both of them were quiet
about it: the Chrome-shaped client hints sent to sign-in hosts, and the settings
page. On Qt 6.11 the engine's default user agent says only ``Chrome/140.0.0.0``,
so a UA-derived "full" version puts a build that never existed into
``sec-ch-ua-full-version`` — the header the fragile Google compatibility path
lives on. ``qWebEngineChromiumVersion()`` knows the real one on both engines.
"""
import unittest
from unittest import mock

from litebrowser.browser import adblock
from litebrowser.services import diagnostics


def _reset_version_cache():
    adblock._CACHED_CHROME_VERSION = None
    adblock._CACHED_CHROME_FULL_VERSION = None


class _RequestInfo:
    """Just enough of Qt's request-info for the header path to run."""

    def __init__(self):
        self.headers = {}

    def setHttpHeader(self, key, value):
        self.headers[bytes(key)] = bytes(value)


class TestClientHintsFollowTheEngine(unittest.TestCase):
    def setUp(self):
        _reset_version_cache()
        self.addCleanup(_reset_version_cache)

    def test_the_binding_answers_without_an_application_object(self):
        with mock.patch.object(adblock, "_engine_chrome_versions", return_value=("140", "140.0.7339.225")):
            major, full = adblock._detect_chrome_versions()
        self.assertEqual((major, full), ("140", "140.0.7339.225"))

    def test_the_binding_wins_over_a_major_only_user_agent(self):
        """The regression that Qt 6.11 exposed: UA says 140.0.0.0, engine knows better."""
        info = _RequestInfo()
        with mock.patch.object(adblock, "_engine_chrome_versions", return_value=("140", "140.0.7339.225")):
            adblock.TrackingBlocker._apply_compat_headers(None, info, "accounts.google.com")
        self.assertEqual(info.headers[b"sec-ch-ua-full-version"], b'"140.0.7339.225"')
        self.assertIn(b'"Chromium";v="140"', info.headers[b"sec-ch-ua"])
        self.assertIn(b'"Google Chrome";v="140"', info.headers[b"sec-ch-ua"])

    def test_the_engine_probe_rejects_a_version_that_is_not_four_parts(self):
        with mock.patch("PyQt5.QtWebEngineCore.qWebEngineChromiumVersion", return_value="", create=True):
            self.assertEqual(adblock._engine_chrome_versions(), ("", ""))

    def test_the_fallback_version_is_shaped_like_a_chrome_build(self):
        """With no engine to ask, send a plausible build rather than an empty header."""
        self.assertTrue(adblock._FALLBACK_CHROME_MAJOR.isdigit())
        self.assertEqual(adblock._FALLBACK_CHROME_FULL.count("."), 3)
        self.assertTrue(adblock._FALLBACK_CHROME_FULL.startswith(adblock._FALLBACK_CHROME_MAJOR + "."))

    def test_a_full_user_agent_yields_the_real_build(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Ch"
        ua += "rome/122.0.6261.171 Safari/537.36"
        self.assertEqual(adblock._ua_chrome_versions(ua), ("122", "122.0.6261.171"))

    def test_the_reduced_qt611_user_agent_is_the_reason_for_the_probe(self):
        """A UA-only build number is zeros — yet it is shaped like a real one."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Ch"
        ua += "rome/140.0.0.0 Safari/537.36"
        self.assertEqual(adblock._ua_chrome_versions(ua), ("140", "140.0.0.0"))

    def test_a_user_agent_with_only_a_major_still_answers(self):
        self.assertEqual(adblock._ua_chrome_versions("Chrome/140"), ("140", "140.0.0.0"))
        self.assertEqual(adblock._ua_chrome_versions(""), ("", ""))


class TestEngineNotice(unittest.TestCase):
    def test_it_names_engine_qt_and_binding(self):
        line = diagnostics.engine_notice({"chromium": "140.0.7339.225", "qt": "6.11.2", "binding": "PyQt6"})
        self.assertEqual(line, "Engine: Chromium 140.0.7339.225 · Qt 6.11.2 · PyQt6")

    def test_the_old_branch_is_flagged_with_the_way_out(self):
        line = diagnostics.engine_notice({"chromium": "87.0.4280.144", "qt": "5.15.2", "binding": "PyQt5"})
        self.assertIn("Chromium 87.0.4280.144", line)
        self.assertIn("PyQt6-WebEngine", line)
        self.assertLess(len(line.splitlines()), 3, "a caution, not an essay")

    def test_the_old_branch_is_flagged_even_with_no_number_to_read(self):
        """PyQt5 cannot answer qWebEngineChromiumVersion() — the case it is for."""
        line = diagnostics.engine_notice({"qt": "5.15.2", "binding": "PyQt5"})
        self.assertIn("Chromium 87", line)
        self.assertIn("PyQt6-WebEngine", line)

    def test_the_new_branch_is_not_warned_about(self):
        line = diagnostics.engine_notice({"chromium": "140.0.7339.225", "qt": "6.11.2", "binding": "PyQt6"})
        self.assertNotIn("PyQt6-WebEngine", line)
        self.assertNotIn("\n", line)

    def test_a_caller_that_could_not_read_anything_shows_nothing(self):
        self.assertEqual(diagnostics.engine_notice({}), "")
        self.assertEqual(diagnostics.engine_notice(None), "")

    def test_it_survives_a_chromium_string_it_cannot_parse(self):
        line = diagnostics.engine_notice({"chromium": "unknown", "binding": "PyQt6"})
        self.assertIn("Chromium unknown", line)
        self.assertNotIn("PyQt6-WebEngine", line, "an unknown engine is not evidence of the old one")


if __name__ == "__main__":
    unittest.main()
