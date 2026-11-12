"""Publisher keys Mei pins for update-manifest verification.

This map ships with ``mei-release-2026b``, the key releases are signed with. An
empty map stays a *valid* state — it means every remote update is refused
("untrusted key"), which is the honest answer for a fork with no publisher key —
but it is no longer the state of this tree, and a build that cannot verify its
own releases cannot update at all. What must never happen is a placeholder pin,
a private key in git, or "skip verification when absent".

To provision or rotate a key (see docs/RELEASE_SIGNING.md for the full runbook):

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
TRUSTED_UPDATE_KEYS: dict[str, str] = {
    'mei-release-2026b': 'wzF8s2ZH/LhUx6SwNpAEC+6wc6et1j485YSIhljgUXc=',
}

#: key ids refused even if present above (compromise response).
REVOKED_UPDATE_KEY_IDS: frozenset[str] = frozenset()

#: The id new releases should sign with; empty while no key is provisioned.
CURRENT_UPDATE_KEY_ID = 'mei-release-2026b'


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
