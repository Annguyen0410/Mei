"""Detached signatures for the update manifest.

A SHA-256 in the manifest proves the *download* matches the manifest. It does
not prove who wrote the manifest: an attacker who can replace both files
replaces the hash too. That is the gap this module closes, by verifying an
Ed25519 signature made by a publisher key that Mei pins out-of-band.

Design rules:

* **Fail closed.** A remote channel with no valid signature is refused. There is
  no "unsigned but probably fine" path, and no silent fallback.
* **Small attack surface.** The signed payload is the manifest itself, encoded
  canonically (sorted keys, no whitespace, no ``signature`` field). Base64 is
  the wire format. No ASN.1, no parsing of attacker-chosen key material.
* **Rotation and revocation.** Each signature names a ``key_id``; Mei looks it
  up in its pinned map and refuses ids listed as revoked. A revoked key stops
  being trusted without shipping a new allowlist format.
* **No private key here, ever.** Only public keys belong in this repository.
  Signing lives in CI with a secret, or on the maintainer's machine.
"""

from __future__ import annotations

import binascii
import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIGNATURE_FIELD = "signature"
KEY_ID_FIELD = "key_id"
#: Excluded from the signed bytes; carries no meaning of its own.
UNSIGNED_FIELDS = (SIGNATURE_FIELD,)
SIGNATURE_ALGORITHM = "ed25519"
RAW_KEY_BYTES = 32


class UpdateSignatureError(ValueError):
    """The manifest is unsigned, malformed, or not signed by a trusted key."""


def canonical_payload(metadata: dict) -> bytes:
    """The exact bytes a publisher signs: deterministic JSON of the manifest.

    ``signature`` is stripped so the payload can be produced from an already
    signed manifest. Everything else is included — dropping a field would let
    an attacker change it without breaking the signature.
    """
    if not isinstance(metadata, dict):
        raise UpdateSignatureError("Update manifest is not a JSON object.")
    body = {key: value for key, value in metadata.items() if key not in UNSIGNED_FIELDS}
    try:
        return json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UpdateSignatureError("Update manifest cannot be canonicalised for signature checking.") from exc


def _decode_public_key(encoded: str) -> Ed25519PublicKey:
    text = str(encoded or "").strip()
    if not text:
        raise UpdateSignatureError("A trusted update key is empty.")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdateSignatureError("A trusted update key is not valid base64.") from exc
    if len(raw) != RAW_KEY_BYTES:
        raise UpdateSignatureError(
            f"A trusted update key must be {RAW_KEY_BYTES} raw Ed25519 bytes, not {len(raw)}."
        )
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise UpdateSignatureError("A trusted update key is not a usable Ed25519 key.") from exc


def _decode_signature(encoded: str) -> bytes:
    text = str(encoded or "").strip()
    if not text:
        raise UpdateSignatureError(
            "This update manifest is not signed. Mei refuses to install a remote "
            "package whose origin cannot be verified (see docs/audit/"
            "MEI_RELEASE_SECURITY_CHECKLIST.md)."
        )
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdateSignatureError("The update manifest signature is not valid base64.") from exc


def verify_manifest(
    metadata: dict,
    trusted_keys: dict[str, str],
    revoked_key_ids=frozenset(),
) -> str:
    """Verify ``metadata`` against pinned keys and return the signing key id.

    Raises :class:`UpdateSignatureError` for every failure mode: no signature,
    unknown key, revoked key, malformed signature, or a bad signature. Callers
    must treat all of them as "do not install".
    """
    signature = metadata.get(SIGNATURE_FIELD) if isinstance(metadata, dict) else None
    key_id = str(metadata.get(KEY_ID_FIELD) or "").strip() if isinstance(metadata, dict) else ""
    if not key_id:
        raise UpdateSignatureError(
            "This update manifest does not name a signing key (key_id). Refusing it."
        )
    if key_id in revoked_key_ids:
        raise UpdateSignatureError(
            f"The update signing key '{key_id}' has been revoked. Refusing this release."
        )
    pinned = trusted_keys.get(key_id) if isinstance(trusted_keys, dict) else None
    if not pinned:
        raise UpdateSignatureError(
            f"The update manifest is signed with an untrusted key ('{key_id}'). "
            "Mei only installs releases signed by a pinned publisher key."
        )
    public_key = _decode_public_key(pinned)
    raw_signature = _decode_signature(signature)
    if len(raw_signature) != 64:
        raise UpdateSignatureError("The update manifest signature has the wrong length.")
    try:
        public_key.verify(raw_signature, canonical_payload(metadata))
    except InvalidSignature as exc:
        raise UpdateSignatureError(
            "The update manifest signature does not match its contents. "
            "The manifest was modified or signed by a different key — refusing it."
        ) from exc
    return key_id


def sign_manifest(metadata: dict, private_key: Ed25519PrivateKey, key_id: str) -> dict:
    """Return a signed copy of ``metadata`` (publishing/testing helper).

    The private key is supplied by the caller and never stored here. Only
    ``tools/publish_release.py`` (with a CI secret) and tests call this.
    """
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("sign_manifest requires an Ed25519PrivateKey")
    body = {key: value for key, value in dict(metadata).items() if key not in UNSIGNED_FIELDS}
    body[KEY_ID_FIELD] = str(key_id)
    body[SIGNATURE_FIELD] = base64.b64encode(private_key.sign(canonical_payload(body))).decode("ascii")
    return body


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    """Base64 raw public key for pinning — the value that goes in update_keys.py."""
    from cryptography.hazmat.primitives import serialization

    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


__all__ = [
    "KEY_ID_FIELD",
    "SIGNATURE_ALGORITHM",
    "SIGNATURE_FIELD",
    "UpdateSignatureError",
    "canonical_payload",
    "public_key_b64",
    "sign_manifest",
    "verify_manifest",
]
