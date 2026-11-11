"""Generate the Ed25519 release-signing key pair for Mei updates.

Run this **once**, offline, by a maintainer — never in CI, never committed:

    python tools/generate_update_key.py --key-id mei-release-2027 --out ~/mei-update-key.txt

It prints the line to paste into ``litebrowser/core/update_keys.py`` and writes
the *private* half to ``--out`` (created with 0600 where the OS honours it).
The private half belongs in the GitHub secret ``MEI_UPDATE_SIGNING_KEY`` (base64
raw 32 bytes) and in the maintainer's password manager; it must never enter git.

Why a tool at all: ``TRUSTED_UPDATE_KEYS`` is deliberately empty and the updater
fails closed until a real public key is pinned, so "the updater is blocked" is a
missing operational step rather than a bug. This script is that step, with the
refusals that make it hard to do carelessly:

* it will not overwrite an existing key file,
* it will not write the private key inside the repository,
* it prints the *public* key only.

Nothing here touches the network.
"""
from __future__ import annotations

import argparse
import base64
import os
import stat
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Running this file directly puts tools/ on sys.path, not the repo root, so the
# litebrowser import below would fail exactly when a maintainer needs the tool.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _inside_repo(path: str) -> bool:
    try:
        target = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(os.path.realpath(REPO_ROOT))
    except OSError:
        return False
    return target == root or target.startswith(root + os.sep)


def _write_private(path: str, secret_b64: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    # Refuse to clobber: a second run would silently orphan the pinned key.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if hasattr(os, "chmod"):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secret_b64)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate Mei's Ed25519 update signing key.")
    parser.add_argument("--key-id", required=True, help="key id to pin, e.g. mei-release-2027")
    parser.add_argument("--out", required=True, help="path for the private key (must be outside the repo)")
    parser.add_argument("--force", action="store_true", help="overwrite --out and any existing key id")
    args = parser.parse_args(argv)

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("error: the 'cryptography' package is required (pip install cryptography>=40)", file=sys.stderr)
        return 2

    if not args.out.strip():
        print("error: --out is required", file=sys.stderr)
        return 2
    if _inside_repo(args.out) and not args.force:
        print(
            "error: refusing to write the private key inside the repository.\n"
            "       Choose a path outside the repository (a password-manager export folder is right).",
            file=sys.stderr,
        )
        return 2
    if os.path.exists(args.out) and not args.force:
        print(
            "error: %s already exists; rotating a pinned key means editing update_keys.py by hand." % args.out,
            file=sys.stderr,
        )
        return 2

    from litebrowser.core import update_keys

    if args.key_id in update_keys.TRUSTED_UPDATE_KEYS and not args.force:
        print("error: key id %r is already pinned" % args.key_id, file=sys.stderr)
        return 2

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(raw_public).decode("ascii")
    private_b64 = base64.b64encode(raw_private).decode("ascii")
    # The secret is stored base64 (raw 32-byte seed), so the file is text: a raw
    # write here produced bytes that no password manager could import.
    if args.force and os.path.exists(args.out):
        os.chmod(args.out, stat.S_IRUSR | stat.S_IWUSR)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(private_b64)
    else:
        _write_private(args.out, private_b64)
    print("Generated Ed25519 release key %r." % args.key_id)
    print()
    print("1. Private key written to: %s  (mode 0600)" % args.out)
    print("2. Paste this into litebrowser/core/update_keys.py:")
    print()
    print("   TRUSTED_UPDATE_KEYS = {")
    print("       %r: %r," % (args.key_id, public_b64))
    print("   }")
    print("   CURRENT_UPDATE_KEY_ID = %r" % args.key_id)
    print()
    print("3. Store the private half as the GitHub secret MEI_UPDATE_SIGNING_KEY:")
    print("   %s" % private_b64)
    print()
    print("4. Also keep it in the maintainer password manager, then delete %s." % args.out)
    print("5. Verify the pin before publishing: python tools/publish_release.py --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
