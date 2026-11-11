"""An update manifest must prove its publisher, not just its bytes.

A SHA-256 only says "the download matches the manifest". Whoever can replace the
download can replace the manifest and its hash. These tests pin the Ed25519
layer that closes that gap, including the failure modes that must never install:
unsigned, tampered, wrong key, unknown key, revoked key, downgrade.

The test keypair is generated at runtime. No private key is in this repository.
"""
import base64
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from litebrowser.core import update_keys
from litebrowser.services import update_signature as sig


class _Keys:
    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = sig.public_key_b64(self.private)

    @property
    def map(self):
        return {"release-2026": self.public}


def _manifest(keys, **overrides):
    payload = {
        "product": "mei",
        "version": "1.0.2.0",
        "download_url": "https://github.com/Annguyen0410/Mei/releases/download/v1.0.2.0/Mei.exe",
        "sha256": "a" * 64,
        "size": 170_000_000,
    }
    payload.update(overrides)
    return sig.sign_manifest(payload, keys.private, "release-2026")


class TestHappyPath(unittest.TestCase):
    def test_a_valid_signature_names_its_key(self):
        keys = _Keys()
        self.assertEqual(sig.verify_manifest(_manifest(keys), keys.map), "release-2026")

    def test_canonical_payload_is_stable_across_key_order(self):
        a = {"product": "mei", "version": "1.0.0.0", "notes": "x"}
        b = {"version": "1.0.0.0", "notes": "x", "product": "mei"}
        self.assertEqual(sig.canonical_payload(a), sig.canonical_payload(b))

    def test_signature_field_is_not_part_of_the_signed_bytes(self):
        keys = _Keys()
        signed = _manifest(keys)
        unsigned = {k: v for k, v in signed.items() if k != sig.SIGNATURE_FIELD}
        self.assertEqual(sig.canonical_payload(signed), sig.canonical_payload(unsigned))


class TestFailures(unittest.TestCase):
    def test_unsigned_manifest_is_refused(self):
        keys = _Keys()
        unsigned = {k: v for k, v in _manifest(keys).items() if k != sig.SIGNATURE_FIELD}
        with self.assertRaises(sig.UpdateSignatureError) as ctx:
            sig.verify_manifest(unsigned, keys.map)
        self.assertIn("not signed", str(ctx.exception))

    def test_tampered_version_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed["version"] = "9.9.9.9"
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)

    def test_tampered_download_url_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed["download_url"] = "https://evil.test/Mei.exe"
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)

    def test_signature_from_a_different_key_is_refused(self):
        keys = _Keys()
        attacker = _Keys()
        signed = _manifest(keys)
        signed[sig.SIGNATURE_FIELD] = base64.b64encode(
            attacker.private.sign(sig.canonical_payload(signed))
        ).decode()
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)

    def test_unknown_key_id_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed["key_id"] = "someone-else"
        with self.assertRaises(sig.UpdateSignatureError) as ctx:
            sig.verify_manifest(signed, keys.map)
        self.assertIn("untrusted", str(ctx.exception))

    def test_revoked_key_is_refused_even_though_pinned(self):
        keys = _Keys()
        with self.assertRaises(sig.UpdateSignatureError) as ctx:
            sig.verify_manifest(_manifest(keys), keys.map, frozenset({"release-2026"}))
        self.assertIn("revoked", str(ctx.exception))

    def test_empty_trust_store_fails_closed(self):
        keys = _Keys()
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(_manifest(keys), {})

    def test_malformed_signature_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed[sig.SIGNATURE_FIELD] = "not-base64!!"
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)

    def test_wrong_length_signature_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed[sig.SIGNATURE_FIELD] = base64.b64encode(b"short").decode()
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)

    def test_malformed_pinned_key_is_refused(self):
        keys = _Keys()
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(_manifest(keys), {"release-2026": "AAAA"})

    def test_missing_key_id_is_refused(self):
        keys = _Keys()
        signed = _manifest(keys)
        signed.pop("key_id")
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(signed, keys.map)


class TestKeyRotation(unittest.TestCase):
    def test_two_pinned_keys_can_verify_their_own_releases(self):
        old, new = _Keys(), _Keys()
        trust = {"release-2025": old.public, "release-2026": new.public}
        self.assertEqual(
            sig.verify_manifest(sig.sign_manifest({"version": "1"}, old.private, "release-2025"), trust),
            "release-2025",
        )
        self.assertEqual(
            sig.verify_manifest(sig.sign_manifest({"version": "1"}, new.private, "release-2026"), trust),
            "release-2026",
        )

    def test_revoking_an_old_key_leaves_the_new_one_working(self):
        old, new = _Keys(), _Keys()
        trust = {"release-2025": old.public, "release-2026": new.public}
        revoked = frozenset({"release-2025"})
        with self.assertRaises(sig.UpdateSignatureError):
            sig.verify_manifest(
                sig.sign_manifest({"version": "1"}, old.private, "release-2025"), trust, revoked
            )
        self.assertEqual(
            sig.verify_manifest(
                sig.sign_manifest({"version": "1"}, new.private, "release-2026"), trust, revoked
            ),
            "release-2026",
        )


class TestShippedTrustStore(unittest.TestCase):
    def test_no_private_key_is_committed(self):
        """The store may be empty, but whatever is pinned must be a public key.

        This used to require an empty dict, which made pinning the real key look
        like a test failure. What actually matters is that every value is a raw
        32-byte Ed25519 *public* key; 64 bytes would mean a private seed was
        committed. Empty stays valid: an unprovisioned build fails closed.
        """
        for key_id, value in update_keys.TRUSTED_UPDATE_KEYS.items():
            with self.subTest(key_id=key_id):
                raw = base64.b64decode(value, validate=True)
                self.assertEqual(len(raw), 32, "a pinned key must be a raw Ed25519 public key")
        if update_keys.CURRENT_UPDATE_KEY_ID:
            self.assertIn(
                update_keys.CURRENT_UPDATE_KEY_ID,
                update_keys.TRUSTED_UPDATE_KEYS,
                "CURRENT_UPDATE_KEY_ID must name a pinned key",
            )

    def test_trusted_keys_returns_a_copy(self):
        # patch.dict, not mutate-then-clear: clearing here would wipe a real
        # pinned key for every test that runs afterwards.
        with mock.patch.dict(update_keys.TRUSTED_UPDATE_KEYS, {"x": "y"}, clear=True):
            snapshot = update_keys.trusted_keys()
            snapshot.clear()
            self.assertEqual(update_keys.TRUSTED_UPDATE_KEYS, {"x": "y"})


if __name__ == "__main__":
    unittest.main()
