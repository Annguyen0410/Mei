"""Password vault compatibility and KDF hardening checks."""
import json
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import password_manager


@unittest.skipUnless(password_manager.HAS_CRYPTO, "cryptography is required")
class TestPasswordManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def _vault_bytes(self):
        with open(password_manager._passwords_path(self.base), "rb") as f:
            return f.read()

    def test_roundtrip_writes_versioned_pbkdf2_vault(self):
        self.assertTrue(password_manager.add_password(self.base, "https://example.com/login", "alice", "secret", "master"))

        envelope = json.loads(self._vault_bytes().decode("utf-8"))
        self.assertEqual(envelope.get("version"), 2)
        self.assertEqual(envelope.get("kdf", {}).get("name"), "pbkdf2-sha256")
        self.assertTrue(envelope.get("kdf", {}).get("salt"))
        self.assertTrue(envelope.get("payload"))

        creds = password_manager.get_credentials_for(self.base, "https://example.com/account", "master")
        self.assertEqual(creds, {"username": "alice", "password": "secret"})

    def test_credentials_never_cross_origins(self):
        self.assertTrue(password_manager.add_password(self.base, "https://example.com/login", "alice", "secret", "master"))
        for url in ("https://example.com.evil.test/", "https://evil-example.com/", "http://example.com/", "https://example.com:444/", "https://example.com@evil.test/"):
            with self.subTest(url=url):
                self.assertFalse(password_manager.get_credentials_for(self.base, url, "master"))
        self.assertEqual(password_manager.get_credentials_for(self.base, "https://example.com:443/account", "master")["username"], "alice")

    def test_legacy_vault_loads_and_resave_migrates_to_v2(self):
        master = "master"
        cipher = password_manager._get_cipher(master)
        self.assertIsNotNone(cipher)

        legacy_payload = [
            {
                "url": "example.com",
                "username": "legacy",
                "password": cipher.encrypt(b"old-secret").decode("utf-8"),
            }
        ]
        legacy_blob = cipher.encrypt(json.dumps(legacy_payload, ensure_ascii=False).encode("utf-8"))
        path = password_manager._passwords_path(self.base)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(legacy_blob)

        creds = password_manager.get_credentials_for(self.base, "https://example.com/login", master)
        self.assertEqual(creds, {"username": "legacy", "password": "old-secret"})

        self.assertTrue(password_manager.add_password(self.base, "https://example.org", "new", "new-secret", master))
        envelope = json.loads(self._vault_bytes().decode("utf-8"))
        self.assertEqual(envelope.get("version"), 2)

    def test_wrong_master_password_never_overwrites_vault(self):
        self.assertTrue(password_manager.add_password(self.base, "https://a.com", "alice", "s1", "correct"))
        self.assertTrue(password_manager.add_password(self.base, "https://b.com", "bob", "s2", "correct"))
        blob_before = self._vault_bytes()

        with self.assertRaises(password_manager.VaultUnlockError):
            password_manager.add_password(self.base, "https://c.com", "carol", "s3", "WRONG")
        self.assertEqual(self._vault_bytes(), blob_before, "vault must be untouched after a wrong master password")

        status, entries = password_manager.load_passwords_status(self.base, "WRONG")
        self.assertEqual(status, "locked")
        self.assertEqual(entries, [])

        # The correct password still works and can add entries afterwards.
        self.assertTrue(password_manager.add_password(self.base, "https://c.com", "carol", "s3", "correct"))
        self.assertEqual(len(password_manager.load_passwords(self.base, "correct")), 3)

    def test_empty_vault_after_legit_clear_still_accepts_saves(self):
        self.assertTrue(password_manager.add_password(self.base, "https://a.com", "alice", "s1", "master"))
        # Simulate a user deleting all entries: an empty-but-valid vault file.
        encoded = password_manager._encode_v2_vault([], "master")
        with open(password_manager._passwords_path(self.base), "wb") as f:
            f.write(encoded)
        status, entries = password_manager.load_passwords_status(self.base, "master")
        self.assertEqual((status, entries), ("ok", []))
        self.assertTrue(password_manager.add_password(self.base, "https://b.com", "bob", "s2", "master"))

    def test_decrypt_failure_does_not_leak_ciphertext(self):
        self.assertTrue(password_manager.add_password(self.base, "https://a.com", "alice", "s1", "master"))
        # Tamper: replace the payload with garbage that still parses as JSON.
        envelope = json.loads(self._vault_bytes().decode("utf-8"))
        envelope["payload"] = "bm90LWEtdmFsaWQtZmVybmV0LXRva2Vu"
        with open(password_manager._passwords_path(self.base), "wb") as f:
            f.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        status, entries = password_manager.load_passwords_status(self.base, "master")
        for entry in entries:
            self.assertNotEqual(entry["password"], "bm90LWEtdmFsaWQtZmVybmV0LXRva2Vu")


class TestAutofillBoundary(unittest.TestCase):
    """F-39: filling a form is releasing a secret, so the page must qualify."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_https_entry_fills_only_on_its_exact_origin(self):
        self.assertTrue(password_manager.add_password(self.base, "https://example.com/login", "alice", "s1", "master"))
        self.assertEqual(
            password_manager.credentials_for_autofill(self.base, "https://example.com/signin", "master"),
            {"username": "alice", "password": "s1"},
        )
        for url in ("https://evil.example.com/", "https://example.com.evil.test/", "https://example.com@evil.test/"):
            with self.subTest(url=url):
                self.assertIsNone(password_manager.credentials_for_autofill(self.base, url, "master"))

    def test_plaintext_http_is_never_autofilled(self):
        self.assertTrue(password_manager.add_password(self.base, "http://example.com/login", "alice", "s1", "master"))
        self.assertFalse(password_manager.autofill_allowed("http://example.com/login"))
        self.assertIsNone(
            password_manager.credentials_for_autofill(self.base, "http://example.com/login", "master"),
            "a cleartext page must not receive a vault secret",
        )

    def test_loopback_http_is_allowed_for_local_development(self):
        self.assertTrue(password_manager.autofill_allowed("http://127.0.0.1:8000/login"))
        self.assertTrue(password_manager.autofill_allowed("http://localhost:3000/"))
        self.assertFalse(password_manager.autofill_allowed("ftp://example.com/"))
        self.assertFalse(password_manager.autofill_allowed(""))

    def test_script_rechecks_the_document_it_lands_in(self):
        script = password_manager.build_autofill_script("alice", "s1", "https://example.com/login")
        self.assertIn('var __lite_expected_origin = "https://example.com"', script)
        self.assertIn("location.origin !== __lite_expected_origin", script)
        self.assertIn("window.top !== window.self", script)
        self.assertIn("target.origin !== location.origin", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("XMLHttpRequest", script)
        self.assertNotIn("fetch(", script)

    def test_script_without_an_origin_fills_nothing(self):
        script = password_manager.build_autofill_script("alice", "s1")
        self.assertIn('var __lite_expected_origin = ""', script)

    def test_the_password_is_json_escaped_not_pasted_in_raw(self):
        password = 'p"a\n</script>\\ end'
        script = password_manager.build_autofill_script("alice", password, "https://example.com")
        self.assertIn(json.dumps(password), script)


class TestAutofillRefusesFormsThatLeakTheUrl(unittest.TestCase):
    """F-40: a GET submission serialises the filled password into the URL."""

    def test_script_requires_a_post_form(self):
        script = password_manager.build_autofill_script("alice", "s1", "https://example.com/login")
        self.assertIn("form.getAttribute('method')", script)
        self.assertIn("method !== 'post'", script)
        # A submit button can override the form's method.
        self.assertIn("formmethod", script)

    def test_same_origin_matches_one_origin_only(self):
        self.assertTrue(password_manager.same_origin("https://example.com/a", "https://example.com/b?c#d"))
        self.assertFalse(password_manager.same_origin("https://example.com/", "https://example.com:8443/"))
        self.assertFalse(password_manager.same_origin("https://example.com/", "https://evil.test/"))
        self.assertFalse(password_manager.same_origin("", ""))


if __name__ == "__main__":
    unittest.main()
