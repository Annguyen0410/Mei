"""Gates for the release-hardening pass: local content, permissions, keys.

Each test here pins a property that was previously only a comment. The two
source-level tests exist because the behaviour they protect needs a live
QWebEnginePage (and a real private profile) to observe, while the invariant —
"private mode never reads the persistent permission file", "no screen turns
LocalContentCanAccessFileUrls back on" — is a property of the code itself.
"""
import base64
import inspect
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from litebrowser.browser import local_content_policy as policy
from litebrowser.core import engine_security, prefs
from litebrowser.services import password_manager
from tools import generate_update_key, publish_release

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestLocalContentPolicy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "web_support")
        os.makedirs(os.path.join(self.root, "Cục Quản Lý"), exist_ok=True)
        self.inside = pathlib.Path(self.root, "Cục Quản Lý", "index.html").as_uri()
        self.outside = pathlib.Path(self._tmp.name, "Downloads", "evil.html").as_uri()

    def tearDown(self):
        self._tmp.cleanup()

    def test_bundled_app_inside_the_trusted_root_is_allowed(self):
        self.assertEqual(policy.navigation_decision(self.inside, (self.root,)), policy.ALLOW)

    def test_downloaded_page_outside_the_root_is_blocked(self):
        self.assertEqual(policy.navigation_decision(self.outside, (self.root,)), policy.BLOCK)

    def test_sibling_folder_with_a_trusted_prefix_is_not_trusted(self):
        # "web_support_old" starts with "web_support" but is a different folder.
        sibling = pathlib.Path(self._tmp.name, "web_support_old", "index.html").as_uri()
        self.assertEqual(policy.navigation_decision(sibling, (self.root,)), policy.BLOCK)

    def test_file_url_with_a_host_authority_is_not_local_content(self):
        # file://fileserver/share/x.html is a network document, not a local one.
        self.assertFalse(policy.is_local_url("file://fileserver/share/x.html"))
        self.assertEqual(policy.navigation_decision("file://fileserver/share/x.html", (self.root,)), policy.ALLOW)

    def test_http_navigation_is_never_gated_here(self):
        for url in ("https://example.com/", "about:blank", "http://localhost:8080/"):
            with self.subTest(url=url):
                self.assertEqual(policy.navigation_decision(url, (self.root,)), policy.ALLOW)

    def test_explicit_opt_in_allows_untrusted_local_files(self):
        self.assertEqual(policy.navigation_decision(self.outside, (self.root,), True), policy.ALLOW)

    def test_no_roots_means_nothing_local_is_trusted(self):
        self.assertEqual(policy.navigation_decision(self.inside, ()), policy.BLOCK)

    def test_unreadable_root_path_is_skipped_not_fatal(self):
        self.assertIsInstance(policy.trusted_local_roots(None, ("", None, "\0bad")), tuple)


class TestPrivateModeDoesNotInheritPermissions(unittest.TestCase):
    def _body(self):
        source = (ROOT / "litebrowser" / "browser" / "browser_page.py").read_text(encoding="utf-8")
        start = source.index("def _on_permission_requested")
        end = source.index("def _trusted_local_roots")
        return source[start:end]

    def test_saved_permission_is_skipped_in_private_mode(self):
        body = self._body()
        self.assertIn("saved = None if incognito else", body, "private tabs must not read the persistent answer")

    def test_private_answer_is_never_persisted(self):
        self.assertIn("if remember and not incognito:", self._body())

    def test_unknown_features_are_denied_without_a_prompt(self):
        body = self._body()
        self.assertIn("if known is None:", body)


class TestWebEngineSettingsPinned(unittest.TestCase):
    def test_browser_profile_never_allows_local_files_to_read_local_files(self):
        source = (ROOT / "litebrowser" / "ui" / "main_window" / "window.py").read_text(encoding="utf-8")
        self.assertNotIn("LocalContentCanAccessFileUrls, True", source)

    def test_personal_view_does_not_widen_the_shared_profile(self):
        source = (ROOT / "litebrowser" / "ui" / "personal_window.py").read_text(encoding="utf-8")
        self.assertNotIn("LocalContentCanAccessFileUrls, True", source)

    def test_navigation_gate_is_installed(self):
        source = (ROOT / "litebrowser" / "browser" / "browser_page.py").read_text(encoding="utf-8")
        self.assertIn("def acceptNavigationRequest", source)
        self.assertIn("policy.BLOCK", source)


class TestEngineSecurityFloor(unittest.TestCase):
    def test_pinned_release_is_known_and_meets_its_own_floor(self):
        entry = engine_security.known_engine("6.11.0")
        self.assertIsNotNone(entry)
        self.assertEqual(entry[0], engine_security.CHROMIUM_BASE)
        self.assertTrue(engine_security.meets_floor(entry[1]))

    def test_unknown_version_does_not_meet_the_floor(self):
        self.assertIsNone(engine_security.security_version_for("9.9.9"))
        self.assertFalse(engine_security.meets_floor(None))

    def test_floor_can_be_compared_directly(self):
        self.assertTrue(engine_security.meets_floor(155, 155))
        self.assertFalse(engine_security.meets_floor(146, 155))


class TestAcceptLanguage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_when_unset(self):
        self.assertEqual(prefs.get_accept_language(self.base), prefs.DEFAULT_ACCEPT_LANGUAGE)

    def test_stored_value_round_trips(self):
        prefs.set_accept_language(self.base, "vi-VN,vi;q=0.9,en;q=0.8")
        self.assertEqual(prefs.get_accept_language(self.base), "vi-VN,vi;q=0.9,en;q=0.8")

    def test_header_injection_is_dropped(self):
        prefs.set_accept_language(self.base, "en-US\r\nX-Evil: 1")
        value = prefs.get_accept_language(self.base)
        self.assertEqual(value, prefs.DEFAULT_ACCEPT_LANGUAGE)
        self.assertNotIn("\n", value)
        self.assertNotIn("\r", value)

    def test_malformed_entries_are_removed_not_passed_through(self):
        cleaned = prefs._clean_accept_language("vi;q=0.9, <script>,en")
        self.assertEqual(cleaned, "vi;q=0.9,en")


class TestLegacyVaultMigration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write_legacy(self, master="master", entries=None):
        cipher = password_manager._get_cipher(master)
        self.assertIsNotNone(cipher)
        items = entries or [
            {"url": "https://example.com", "username": "legacy", "password": cipher.encrypt(b"secret").decode()},
        ]
        blob = cipher.encrypt(json.dumps(items).encode("utf-8")).decode("utf-8")
        path = password_manager._passwords_path(self.base)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(blob)
        return path

    def test_unlocking_a_legacy_vault_rewrites_it_as_v2(self):
        path = self._write_legacy()
        status, entries = password_manager.load_passwords_status(self.base, "master")
        self.assertEqual(status, "ok")
        self.assertEqual(entries, [{"url": "https://example.com", "username": "legacy", "password": "secret"}])

        with open(path, "r", encoding="utf-8") as f:
            envelope = json.load(f)
        self.assertEqual(envelope.get("version"), 2)
        self.assertEqual(envelope.get("kdf", {}).get("name"), "pbkdf2-sha256")
        # The migrated file still opens with the same master password.
        self.assertEqual(password_manager.load_passwords(self.base, "master")[0]["password"], "secret")

    def test_wrong_password_leaves_the_legacy_file_untouched(self):
        path = self._write_legacy()
        with open(path, "r", encoding="utf-8") as f:
            before = f.read()
        status, entries = password_manager.load_passwords_status(self.base, "wrong")
        self.assertEqual((status, entries), ("locked", []))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_add_password_still_refuses_a_locked_vault(self):
        self._write_legacy()
        with self.assertRaises(password_manager.VaultUnlockError):
            password_manager.add_password(self.base, "https://other.test", "u", "p", "wrong")


class TestUpdateKeyTool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self._tmp.name, "mei-update-key.txt")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv):
        out = []
        err = []
        code = 0
        with mock.patch("sys.stdout", new_callable=lambda: _Sink(out)), \
             mock.patch("sys.stderr", new_callable=lambda: _Sink(err)):
            code = generate_update_key.main(argv)
        return code, "".join(out), "".join(err)

    def test_generates_a_32_byte_public_key_and_prints_the_pin(self):
        code, out, _err = self._run(["--key-id", "test-key", "--out", self.out])
        self.assertEqual(code, 0)
        raw = base64.b64decode(open(self.out, encoding="utf-8").read().strip(), validate=True)
        self.assertEqual(len(raw), 32)
        self.assertIn("TRUSTED_UPDATE_KEYS = {", out)
        self.assertIn("test-key", out)
        self.assertIn("MEI_UPDATE_SIGNING_KEY", out)

    def test_refuses_to_write_the_private_key_inside_the_repository(self):
        inside = os.path.join(str(ROOT), "should-not-exist.key")
        code, _out, err = self._run(["--key-id", "test-key", "--out", inside])
        self.assertEqual(code, 2)
        self.assertIn("outside the repository", err)
        self.assertFalse(os.path.exists(inside))

    def test_refuses_to_overwrite_an_existing_key_file(self):
        self.assertEqual(self._run(["--key-id", "test-key", "--out", self.out])[0], 0)
        code, _out, err = self._run(["--key-id", "test-key", "--out", self.out])
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)


class TestInstallerIsAttachedToReleases(unittest.TestCase):
    """A release used to ship Mei.exe plus an archive, with no installer.

    installer.iss existed and Inno Setup is free; nothing ever built it, which
    is why v1.0.1.0 has no MeiSetup.exe. These checks keep the wiring from
    disappearing again.
    """

    def test_publish_accepts_an_installer_path(self):
        self.assertIn("installer", inspect.signature(publish_release.publish).parameters)

    def test_default_installer_path_is_meisetup(self):
        self.assertTrue(publish_release.DEFAULT_INSTALLER.replace("\\", "/").endswith("dist/MeiSetup.exe"))

    def test_usage_documents_the_flag(self):
        self.assertIn("--installer", publish_release.USAGE)

    def test_workflow_builds_and_attaches_the_installer(self):
        source = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("ISCC.exe", source, "the workflow must compile installer.iss")
        self.assertIn('"dist/MeiSetup.exe"', source)
        self.assertIn("--installer", source, "the installer must reach the release")

    def test_signing_step_no_longer_requires_an_exportable_pfx(self):
        source = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("/f $pfx", source)
        self.assertIn("trusted-signing-action", source)


class _Sink:
    """Minimal write-only stand-in for stdout/stderr in the tool test."""

    def __init__(self, store):
        self._store = store

    def write(self, text):
        self._store.append(text)

    def flush(self):
        pass


if __name__ == "__main__":
    unittest.main()
