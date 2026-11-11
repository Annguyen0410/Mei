"""Publisher keys Mei pins for update-manifest verification.

**This map is intentionally empty until a real publisher key exists.** An empty
map means every remote update is refused ("untrusted key"): fail closed. That is
the honest state — Mei has no signing key yet, so it cannot prove a release came
from its publisher, and pretending otherwise (a placeholder key, a generated
key committed to the repo, or "skip verification if absent") would be worse than
not updating at all.

To provision it, once (see docs/RELEASE_SIGNING.md for the full runbook):

1. Run ``python tools/generate_update_key.py --key-id mei-release-2026 --out <file
   outside this repo>``. It prints the block below and the private half, and
   refuses to write a key into the repository.
2. Store the private half only as the CI secret ``MEI_UPDATE_SIGNING_KEY``
   (base64 raw 32 bytes) and in the maintainer's password manager.
3. Put its base64 **public** key in ``TRUSTED_UPDATE_KEYS`` under that key id and
   set ``CURRENT_UPDATE_KEY_ID`` to it. The matching private half must never be
   in git.
4. Rotate by adding the new id *while the old one is still pinned*, ship one
   release that carries both, then switch the publisher and remove the old pin.

Revocation: list an id in ``REVOKED_UPDATE_KEY_IDS`` and ship a patch release.
A revoked key is refused even though it is still pinned, which is why rotation
must publish a new id rather than reuse the compromised one.
"""

from __future__ import annotations

#: key_id -> base64 raw Ed25519 public key (32 bytes). Empty = fail closed.
TRUSTED_UPDATE_KEYS: dict[str, str] = {}

#: key ids refused even if present above (compromise response).
REVOKED_UPDATE_KEY_IDS: frozenset[str] = frozenset()

#: The id new releases should sign with; empty while no key is provisioned.
CURRENT_UPDATE_KEY_ID = ""


def trusted_keys() -> dict[str, str]:
    """A copy, so a caller cannot mutate the pinned allowlist."""
    return dict(TRUSTED_UPDATE_KEYS)


def signing_configured() -> bool:
    """True when this build can verify a remote release at all."""
    return bool(TRUSTED_UPDATE_KEYS) and bool(CURRENT_UPDATE_KEY_ID)


__all__ = [
    "CURRENT_UPDATE_KEY_ID",
    "REVOKED_UPDATE_KEY_IDS",
    "TRUSTED_UPDATE_KEYS",
    "signing_configured",
    "trusted_keys",
]
