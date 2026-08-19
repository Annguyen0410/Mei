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


if __name__ == "__main__":
    unittest.main()
