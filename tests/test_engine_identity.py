"""The browser must describe itself truthfully.

Mei used to inject a DocumentCreation script on every profile that deleted
``navigator.webdriver``, replaced ``navigator.plugins``, invented
``deviceMemory`` and rewrote WebGL's unmasked vendor/renderer strings — in the
main world and in every subframe. That is fingerprint spoofing, not a
compatibility fix, and these tests keep it from coming back:

* the UA names Mei and the real Chromium major, never "Google Chrome";
* the only compat allowlist is sign-in origins, matched exactly by suffix;
* the compat headers report Chromium/Mei, not a Chrome install;
* ``browser_page`` contains no spoofing script and its install hook only removes;
* ``pyproject``/``requirements`` pin one production engine.
"""
import os
import unittest

from litebrowser.browser import engine_identity

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeProfile:
    def __init__(self, user_agent):
        self._ua = user_agent

    def httpUserAgent(self):
        return self._ua


class TestTruthfulUserAgent(unittest.TestCase):
    def test_ua_names_mei_and_keeps_the_real_chromium_major(self):
        with unittest.mock.patch.object(engine_identity, "chromium_version", return_value=("140", "140.0.7339.225")):
            ua = engine_identity.build_user_agent(mei_version="1.2.3.4")
        self.assertIn("Mei/1.2.3.4", ua)
        self.assertIn("Chrome/140.0.0.0", ua)

    def test_ua_never_claims_to_be_google_chrome(self):
        with unittest.mock.patch.object(engine_identity, "chromium_version", return_value=("140", "140.0.7339.225")):
            ua = engine_identity.build_user_agent()
        self.assertNotIn("Google Chrome", ua)
        self.assertNotIn("QtWebEngine", ua, "CDNs serve unsupported pages to that token")
        self.assertNotIn("QtWebEngine", ua)

    def test_unknown_version_is_omitted_not_invented(self):
        with unittest.mock.patch.object(engine_identity, "chromium_version", return_value=("", "")):
            ua = engine_identity.build_user_agent(mei_version="1.0.0.0")
        self.assertNotIn("Chrome/", ua)
        self.assertIn("Mei/1.0.0.0", ua)

    def test_version_is_read_from_the_binding_first(self):
        profile = _FakeProfile("Mozilla/5.0 Chrome/122.0.6261.171 Safari/537.36")
        with unittest.mock.patch.object(engine_identity, "chromium_version", return_value=("140", "140.0.7339.225")):
            self.assertEqual(engine_identity.build_user_agent(profile).count("Chrome/140.0.0.0"), 1)

    def test_profile_ua_is_only_a_fallback(self):
        # Direct call to the fallback path, with the binding unavailable.
        profile = _FakeProfile("Mozilla/5.0 Chrome/122.0.6261.171 Safari/537.36")
        major, full = engine_identity._CHROME_RE.search(profile.httpUserAgent()).groups()[:2]
        self.assertEqual(major, "122")


class TestSignInAllowlist(unittest.TestCase):
    def test_sign_in_origins_match(self):
        for host in ("accounts.google.com", "chatgpt.com", "auth.openai.com", "claude.ai"):
            with self.subTest(host=host):
                self.assertTrue(engine_identity.is_sign_in_host(host))

    def test_subdomains_match_but_suffix_tricks_do_not(self):
        self.assertTrue(engine_identity.is_sign_in_host("login.accounts.google.com"))
        self.assertFalse(engine_identity.is_sign_in_host("evilaccounts.google.com"))
        self.assertFalse(engine_identity.is_sign_in_host("google.com.evil.test"))

    def test_ordinary_browsing_hosts_are_not_allowlisted(self):
        for host in ("example.com", "wikipedia.org", "github.com", "localhost", ""):
            with self.subTest(host=host):
                self.assertFalse(engine_identity.is_sign_in_host(host))


class TestClientHints(unittest.TestCase):
    def test_brands_are_chromium_and_mei_not_chrome(self):
        headers = engine_identity.client_hint_headers("140", "140.0.7339.225")
        self.assertIn(b'"Chromium";v="140"', headers[b"sec-ch-ua"])
        self.assertIn(b'"Mei";v=', headers[b"sec-ch-ua"])
        self.assertNotIn(b"Google Chrome", headers[b"sec-ch-ua"])

    def test_values_come_from_the_real_engine(self):
        headers = engine_identity.client_hint_headers("140", "140.0.7339.225")
        self.assertEqual(headers[b"sec-ch-ua-full-version"], b'"140.0.7339.225"')
        self.assertIn(b"140.0.7339.225", headers[b"sec-ch-ua-full-version-list"])

    def test_unknown_engine_sends_no_hints(self):
        self.assertEqual(engine_identity.client_hint_headers("", ""), {})

    def test_mismatched_full_version_is_shaped_to_the_major(self):
        headers = engine_identity.client_hint_headers("140", "122.0.1.2")
        self.assertEqual(headers[b"sec-ch-ua-full-version"], b'"140.0.0.0"')


class TestNoGlobalSpoofingScript(unittest.TestCase):
    def _source(self, relpath):
        with open(os.path.join(ROOT, relpath), encoding="utf-8") as handle:
            return handle.read()

    def test_browser_page_has_no_fingerprint_fabrication(self):
        source = self._source(os.path.join("litebrowser", "browser", "browser_page.py"))
        for marker in (
            "tryDefine(",
            "makeNative(",
            "UNMASKED_RENDERER",
            "UNMASKED_VENDOR",
            "Object.defineProperty(navigator",
            "navigator.plugins =",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_the_compat_hook_only_uninstalls(self):
        source = self._source(os.path.join("litebrowser", "browser", "browser_page.py"))
        self.assertIn("LEGACY_CHROME_SHIM_REMOVED", source)
        start = source.index("def ensure_chrome_compat_script(")
        end = source.index("class BrowserPage(")
        body = source[start:end]
        self.assertNotIn("scripts.insert", body)
        self.assertIn("scripts.remove", body)

    def test_no_chrome_impersonation_brand_is_sent(self):
        source = self._source(os.path.join("litebrowser", "browser", "adblock.py"))
        self.assertNotIn('"Google Chrome";v=', source)


class TestSingleProductionEngine(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def test_pyproject_defaults_to_qt6_pinned(self):
        text = self._read("pyproject.toml")
        project = text.split("[project]", 1)[1].split("[project.optional-dependencies]", 1)[0]
        deps = project.split("dependencies = [", 1)[1].split("]", 1)[0]
        self.assertIn('"PyQt6==6.11.0"', deps)
        self.assertIn('"PyQt6-WebEngine==6.11.0"', deps)
        self.assertNotIn("PyQt5", deps, "a default install must not pick Chromium 87")

    def test_pyqt5_is_documented_as_legacy_only(self):
        text = self._read("pyproject.toml")
        self.assertIn("qt5 = [", text)
        self.assertIn("LEGACY", text)

    def test_requirements_pin_the_same_engine(self):
        text = self._read("requirements.txt")
        self.assertIn("PyQt6==6.11.0", text)
        self.assertIn("PyQt6-WebEngine==6.11.0", text)
        self.assertNotIn("PyQt5>=", text)


if __name__ == "__main__":
    unittest.main()
