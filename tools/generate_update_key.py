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
import ast
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


def _module_path() -> str:
    return os.path.join(REPO_ROOT, "litebrowser", "core", "update_keys.py")


def _assignment_span(source: str, name: str):
    """1-based (first, last) line of the assignment to ``name``, or ``None``."""
    tree = ast.parse(source)
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if getattr(target, "id", "") == name and getattr(node, "end_lineno", None):
            return node.lineno, node.end_lineno
    return None


def _literal_after_equals(block: str):
    """Value of an ``X = <literal>`` / ``X: T = <literal>`` source block."""
    return ast.literal_eval(block.split("=", 1)[1].strip())


def pin_public_key(key_id: str, public_b64: str, module_path: str) -> str:
    """Pin ``key_id`` in ``TRUSTED_UPDATE_KEYS`` and make it the current key.

    Returns the previous ``CURRENT_UPDATE_KEY_ID`` (``""`` when none). A rotation
    keeps every existing pin, because an installed build must still be able to
    verify a release signed by the key it already trusts.

    Raises ``ValueError`` when the file does not look like the pin module, so a
    wrong path cannot be rewritten, and when the existing pins are not literals
    (they would be lost by a textual rewrite).
    """
    with open(module_path, encoding="utf-8") as handle:
        source = handle.read()
    lines = source.splitlines()

    keys_span = _assignment_span(source, "TRUSTED_UPDATE_KEYS")
    if keys_span is None:
        raise ValueError("%s has no TRUSTED_UPDATE_KEYS assignment" % module_path)
    current_span = _assignment_span(source, "CURRENT_UPDATE_KEY_ID")
    if current_span is None:
        raise ValueError("%s has no CURRENT_UPDATE_KEY_ID assignment" % module_path)

    try:
        existing = dict(_literal_after_equals("\n".join(lines[keys_span[0] - 1 : keys_span[1]])) or {})
    except (SyntaxError, ValueError, TypeError) as exc:
        raise ValueError("existing pins in %s are not a plain dict: %s" % (module_path, exc)) from exc
    try:
        previous_current = str(
            _literal_after_equals("\n".join(lines[current_span[0] - 1 : current_span[1]])) or ""
        )
    except (SyntaxError, ValueError, TypeError):
        previous_current = ""

    pins = dict(existing)
    pins[key_id] = public_b64
    new_keys = ["TRUSTED_UPDATE_KEYS: dict[str, str] = {"]
    new_keys += ["    %r: %r," % (k, v) for k, v in pins.items()]
    new_keys.append("}")
    new_current = ["CURRENT_UPDATE_KEY_ID = %r" % key_id]

    # Replace the later block first so the earlier line numbers stay valid.
    for span, replacement in sorted(((current_span, new_current), (keys_span, new_keys)),
                                    key=lambda item: item[0][0], reverse=True):
        lines[span[0] - 1 : span[1]] = replacement
    updated = "\n".join(lines) + "\n"

    # Atomic replace: a half-written update_keys.py would break every import.
    temporary = module_path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    os.replace(temporary, module_path)
    return previous_current


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate Mei's Ed25519 update signing key.")
    parser.add_argument("--key-id", required=True, help="key id to pin, e.g. mei-release-2027")
    parser.add_argument("--out", required=True, help="path for the private key (must be outside the repo)")
    parser.add_argument("--force", action="store_true", help="overwrite --out and any existing key id")
    parser.add_argument(
        "--print-private",
        action="store_true",
        help=(
            "also print the private key — it then lives in terminal scrollback and in any "
            "log or screenshot you share; only do this on a machine you control"
        ),
    )
    parser.add_argument("--pin", action="store_true", help="write the public key into update_keys.py instead of printing the block")
    parser.add_argument("--module", default="", help="path to update_keys.py (default: the one in this repository)")
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
    # A PowerShell expression pasted into cmd.exe arrives here unexpanded, and the
    # literal string then resolves *inside* the repository — where this tool
    # refuses to write. Name the real cause instead of a confusing refusal.
    lowered_out = args.out.lower()
    for token in ("$env:", "${", "%userprofile%", "%appdata%", "%temp%", "<", ">"):
        if token in lowered_out:
            print(
                "error: --out contains '%s', which your shell did not expand.\n"
                "       cmd.exe:    %%USERPROFILE%%\\mei-key.txt\n"
                "       PowerShell: \"$env:USERPROFILE\\mei-key.txt\"" % token,
                file=sys.stderr,
            )
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

    if args.pin:
        try:
            previous = pin_public_key(args.key_id, public_b64, args.module or _module_path())
        except (OSError, ValueError) as exc:
            print("error: could not pin the key: %s" % exc, file=sys.stderr)
            return 2
        print("Pinned %r in %s" % (args.key_id, args.module or _module_path()))
        if previous and previous != args.key_id:
            print("   %r stays pinned too (keep it until every shipped build can verify the new key)" % previous)
        else:
            print("   CURRENT_UPDATE_KEY_ID now points at it")
        print("   next: rebuild the exe (the key is part of the app) and run")
        print("         python -m pytest tests/test_update_signature.py tests/test_release_hardening.py")
        print()
    print("1. Private key written to: %s  (mode 0600)" % args.out)
    if args.pin:
        print("2. update_keys.py already carries %r (done by --pin)." % args.key_id)
    else:
        print("2. Paste this into litebrowser/core/update_keys.py:")
        print()
        print("   TRUSTED_UPDATE_KEYS = {")
        print("       %r: %r," % (args.key_id, public_b64))
        print("   }")
        print("   CURRENT_UPDATE_KEY_ID = %r" % args.key_id)
        print()
        print("   (or re-run with --pin and this file is updated for you)")
    print()
    # The private half is deliberately NOT printed. Printing it put a live
    # signing key into a terminal scrollback, which is how it ends up in a pasted
    # bug report — a leaked key is worse than an inconvenient one.
    print("3. Store the private half as the GitHub secret MEI_UPDATE_SIGNING_KEY.")
    print("   It is deliberately NOT printed: read it from %s" % args.out)
    if args.print_private:
        print("   --print-private was passed, so: %s" % private_b64)
    print()
    print("4. Also keep it in the maintainer password manager, then delete %s." % args.out)
    print("5. Verify the pin before publishing: python tools/publish_release.py --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
