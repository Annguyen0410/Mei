"""Authenticated, password-encrypted backup containers.

This module wraps the existing verified profile ZIP in a versioned container.
It deliberately does not replace that format: legacy ``.mei-backup.zip`` files
remain importable, while an encrypted backup is a separate
``.mei-backup.enc`` artifact.

Cryptography uses maintained primitives from ``cryptography``:

* AES-256-GCM for authenticated encryption;
* scrypt for password-based key derivation;
* a fresh 16-byte salt and 12-byte nonce for every archive;
* the versioned header as GCM associated data.

The encrypted header is authenticated before any archive is published.  A
wrong password, modified header, modified ciphertext, modified tag or truncated
file all fail authentication.  Decryption writes only to a private temporary
file outside the live profile; the inner ZIP is verified before a restore ever
sees it.

There is intentionally no recovery key and no password reset.  A lost password
means the backup cannot be decrypted.  The password is never stored in prefs,
logs, the profile or the container.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from litebrowser.core.log import get_logger
from litebrowser.core.storage_utils import _atomic_replace, tempfile_mkstemp_same_dir
from litebrowser.services import backup_service

_log = get_logger("encrypted_backup")

MAGIC = backup_service.ENCRYPTED_MAGIC
FORMAT_VERSION = 1
EXTENSION = backup_service.ENCRYPTED_EXTENSION
CIPHER = "AES-256-GCM"
KDF = "scrypt"
TAG_BYTES = 16
HEADER_MAX_BYTES = 16 * 1024
MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_BYTES = 1024
SALT_BYTES = 16
NONCE_BYTES = 12
KEY_BYTES = 32
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
MIN_SCRYPT_N = 2**14
MAX_SCRYPT_N = 2**18
MAX_SCRYPT_R = 16
MAX_SCRYPT_P = 4
MAX_ENCRYPTED_BYTES = backup_service.MAX_TOTAL_BYTES + 32 * 1024 * 1024
_LOCK = threading.Lock()
PRIVATE_TEMP_DIR_NAME = "MeiSecureTemp"
STALE_TEMP_SECONDS = 24 * 60 * 60


class EncryptedBackupError(OSError):
    """An encrypted container could not be created, read or authenticated."""

    def __init__(self, message: str, *, status: str = "invalid"):
        super().__init__(message)
        self.status = status


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise EncryptedBackupError("A password is required.", status="password_required")
    data = password.encode("utf-8")
    if not data:
        raise EncryptedBackupError("A password is required.", status="password_required")
    if len(data) > MAX_PASSWORD_BYTES:
        raise EncryptedBackupError("The password is too long.", status="invalid_password")
    return data


def _strict_int(value) -> int:
    """Header integers must be actual JSON integers, never coercible strings."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncryptedBackupError("Encrypted header parameters are invalid.", status="invalid_header")
    return value


def _strict_hex(value, length: int) -> bytes:
    if not isinstance(value, str) or len(value) != length * 2:
        raise EncryptedBackupError("Encrypted header parameters are invalid.", status="invalid_header")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise EncryptedBackupError("Encrypted header parameters are invalid.", status="invalid_header") from exc
    if len(decoded) != length:
        raise EncryptedBackupError("Encrypted header parameters are invalid.", status="invalid_header")
    return decoded


def _private_temp_root() -> str:
    """A Mei-owned private directory, not the shared user temp directory."""
    root = os.path.join(tempfile.gettempdir(), PRIVATE_TEMP_DIR_NAME)
    os.makedirs(root, mode=0o700, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _private_temp_dir(prefix: str) -> str:
    path = os.path.join(_private_temp_root(), f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path, mode=0o700, exist_ok=False)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def cleanup_stale_temp(*, now: int | None = None, max_age: int = STALE_TEMP_SECONDS) -> list[str]:
    """Remove only abandoned Mei-owned plaintext temp files.

    The caller may have crashed before ``finally`` ran.  Every candidate must be
    directly under the private root, must not be a symlink, and must be older
    than ``max_age``.  Unrelated files and recent in-flight work are untouched.
    """
    root = os.path.realpath(_private_temp_root())
    cutoff = int(now if now is not None else time.time()) - max(0, int(max_age))
    removed: list[str] = []
    try:
        names = os.listdir(root)
    except OSError:
        return removed
    for name in names:
        path = os.path.join(root, name)
        try:
            if os.path.islink(path) or os.path.realpath(os.path.dirname(path)) != root:
                continue
            stat = os.lstat(path)
            if stat.st_mtime > cutoff:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=False)
            else:
                os.unlink(path)
            removed.append(path)
        except OSError as exc:
            _log.warning("could not clean stale encrypted-backup temp %s: %s", path, exc)
    return removed


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
        raise EncryptedBackupError(
            "Encrypted backup requested an unsupported KDF configuration.",
            status="invalid_kdf",
        )
    data = _password_bytes(password)
    try:
        return Scrypt(salt=salt, length=KEY_BYTES, n=n, r=r, p=p).derive(data)
    except (TypeError, ValueError, MemoryError) as exc:
        raise EncryptedBackupError("The backup key could not be derived.", status="invalid_kdf") from exc


def _read_header(path: str) -> tuple[dict, int, bytes]:
    if not os.path.isfile(path):
        raise EncryptedBackupError("Encrypted backup does not exist.", status="missing")
    try:
        size = os.path.getsize(path)
        if size < len(MAGIC) + 4 + TAG_BYTES:
            raise EncryptedBackupError("Encrypted backup is truncated.", status="truncated")
        if size > MAX_ENCRYPTED_BYTES:
            raise EncryptedBackupError("Encrypted backup is too large.", status="too_large")
        with open(path, "rb") as handle:
            if handle.read(len(MAGIC)) != MAGIC:
                raise EncryptedBackupError("Not a Mei encrypted backup.", status="unrecognised")
            raw_len = handle.read(4)
            if len(raw_len) != 4:
                raise EncryptedBackupError("Encrypted header is truncated.", status="truncated")
            header_len = struct.unpack(">I", raw_len)[0]
            if header_len <= 0 or header_len > HEADER_MAX_BYTES:
                raise EncryptedBackupError("Encrypted header has an invalid size.", status="invalid_header")
            raw_header = handle.read(header_len)
            if len(raw_header) != header_len:
                raise EncryptedBackupError("Encrypted header is truncated.", status="truncated")
    except EncryptedBackupError:
        raise
    except OSError as exc:
        raise EncryptedBackupError(f"Could not read encrypted backup: {exc}", status="unreadable") from exc
    try:
        header = json.loads(raw_header.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EncryptedBackupError("Encrypted header is not valid JSON.", status="invalid_header") from exc
    if not isinstance(header, dict):
        raise EncryptedBackupError("Encrypted header is not an object.", status="invalid_header")
    if _strict_int(header.get("format_version")) != FORMAT_VERSION:
        raise EncryptedBackupError("Unsupported encrypted backup format.", status="incompatible")
    if header.get("cipher") != CIPHER or header.get("kdf") != KDF:
        raise EncryptedBackupError("Unsupported encrypted backup algorithm.", status="incompatible")
    n = _strict_int(header.get("n"))
    r = _strict_int(header.get("r"))
    p = _strict_int(header.get("p"))
    _salt = _strict_hex(header.get("salt"), SALT_BYTES)
    _nonce = _strict_hex(header.get("nonce"), NONCE_BYTES)
    inner_size = _strict_int(header.get("inner_size"))
    created_at = _strict_int(header.get("created_at"))
    inner_sha = header.get("inner_sha256")
    if not isinstance(inner_sha, str) or len(inner_sha) != 64:
        raise EncryptedBackupError("Encrypted header checksum is invalid.", status="invalid_header")
    if (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
        # Version 1 has exactly one approved KDF configuration.  Reject before
        # calling scrypt so a hostile header cannot request unbounded work.
        raise EncryptedBackupError(
            "Encrypted header requests an unsupported KDF configuration.",
            status="invalid_kdf",
        )
    if (
        created_at < 0
        or inner_size < 0
        or inner_size > backup_service.MAX_TOTAL_BYTES + backup_service.MAX_FILE_BYTES
    ):
        raise EncryptedBackupError("Encrypted header parameters are outside safe limits.", status="invalid_header")
    offset = len(MAGIC) + 4 + header_len
    ciphertext_size = size - offset - TAG_BYTES
    if ciphertext_size <= 0:
        raise EncryptedBackupError("Encrypted payload is truncated.", status="truncated")
    if ciphertext_size != inner_size:
        raise EncryptedBackupError("Encrypted payload length does not match its header.", status="invalid_header")
    aad = MAGIC + struct.pack(">I", header_len) + raw_header
    return header, offset, aad


def is_encrypted(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def inspect(path: str) -> dict:
    """Read the authenticated-format header without decrypting any payload."""
    try:
        header, _offset, _aad = _read_header(path)
        return {
            "ok": True,
            "status": "encrypted",
            "encrypted": True,
            "header": header,
            "created_at": int(header.get("created_at") or 0),
            "inner_size": int(header.get("inner_size") or 0),
            "error": "",
        }
    except EncryptedBackupError as exc:
        return {
            "ok": False,
            "status": exc.status,
            "encrypted": True,
            "header": {},
            "created_at": 0,
            "error": str(exc),
        }


def _header(
    *,
    created_at: int,
    inner_size: int,
    inner_sha256: str,
    salt: bytes,
    nonce: bytes,
) -> dict:
    return {
        "kind": "mei.encrypted_backup",
        "format_version": FORMAT_VERSION,
        "cipher": CIPHER,
        "kdf": KDF,
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "created_at": int(created_at),
        "inner_size": int(inner_size),
        "inner_sha256": str(inner_sha256),
    }


def _encrypt_archive(archive_path: str, output_path: str, password: str, *, created_at: int) -> dict:
    _password_bytes(password)
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = _derive_key(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    try:
        size = os.path.getsize(archive_path)
        if size > backup_service.MAX_TOTAL_BYTES + backup_service.MAX_FILE_BYTES:
            raise EncryptedBackupError("Archive is too large to encrypt.", status="too_large")
        digest = hashlib.sha256()
        with open(archive_path, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        header = _header(
            created_at=created_at,
            inner_size=size,
            inner_sha256=digest.hexdigest(),
            salt=salt,
            nonce=nonce,
        )
        raw_header = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw_header) > HEADER_MAX_BYTES:
            raise EncryptedBackupError("Encrypted header is too large.", status="invalid_header")
        length_prefix = struct.pack(">I", len(raw_header))
        aad = MAGIC + length_prefix + raw_header
        parent = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(parent, exist_ok=True)
        fd, temporary = tempfile_mkstemp_same_dir(parent, os.path.basename(output_path))
        try:
            with open(archive_path, "rb") as source, os.fdopen(fd, "wb") as target:
                target.write(MAGIC)
                target.write(length_prefix)
                target.write(raw_header)
                encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
                encryptor.authenticate_additional_data(aad)
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    target.write(encryptor.update(block))
                target.write(encryptor.finalize())
                target.write(encryptor.tag)
                target.flush()
                os.fsync(target.fileno())
            _atomic_replace(temporary, output_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    finally:
        # Best effort: Python cannot guarantee zeroisation of immutable bytes.
        key = b""
    return header


def decrypt_to_temp(path: str, password: str) -> tuple[str, dict]:
    """Authenticate and decrypt to a private temp ZIP, then verify its manifest.

    The returned file must be consumed promptly and deleted by the caller.  It
    never lives inside the active profile.
    """
    header, offset, aad = _read_header(path)
    key = _derive_key(password, bytes.fromhex(header["salt"]), int(header["n"]), int(header["r"]), int(header["p"]))
    nonce = bytes.fromhex(header["nonce"])
    size = os.path.getsize(path)
    ciphertext_size = size - offset - TAG_BYTES
    if ciphertext_size <= 0:
        raise EncryptedBackupError("Encrypted payload is truncated.", status="truncated")
    fd, plain_path = tempfile_mkstemp_same_dir(_private_temp_root(), "decrypted.zip")
    try:
        os.chmod(plain_path, 0o600)
    except OSError:
        pass
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as source, os.fdopen(fd, "wb") as target:
            source.seek(offset)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).decryptor()
            decryptor.authenticate_additional_data(aad)
            remaining = ciphertext_size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise EncryptedBackupError("Encrypted payload is truncated.", status="truncated")
                remaining -= len(block)
                plain = decryptor.update(block)
                digest.update(plain)
                target.write(plain)
            tag = source.read(TAG_BYTES)
            if len(tag) != TAG_BYTES:
                raise EncryptedBackupError("Encrypted authentication tag is truncated.", status="truncated")
            try:
                plain = decryptor.finalize_with_tag(tag)
            except InvalidTag as exc:
                raise EncryptedBackupError(
                    "Authentication failed: wrong password or modified backup.",
                    status="authentication_failed",
                ) from exc
            digest.update(plain)
            target.write(plain)
            target.flush()
            os.fsync(target.fileno())
        if digest.hexdigest() != str(header.get("inner_sha256") or ""):
            raise EncryptedBackupError("Decrypted archive checksum does not match its header.", status="invalid_content")
        checked = backup_service.verify_backup(plain_path)
        if not checked.get("ok"):
            raise EncryptedBackupError(
                "Decrypted archive failed Mei backup verification: "
                + "; ".join(checked.get("errors") or []),
                status="invalid_content",
            )
        return plain_path, header
    except Exception:
        try:
            os.unlink(plain_path)
        except OSError:
            pass
        raise
    finally:
        key = b""


def verify_encrypted(path: str, password: str) -> dict:
    """Fully authenticate, decrypt and verify an encrypted backup."""
    try:
        plain_path, header = decrypt_to_temp(path, password)
        try:
            checked = backup_service.verify_backup(plain_path)
        finally:
            try:
                os.unlink(plain_path)
            except OSError:
                pass
        checked["encrypted"] = True
        checked["encrypted_header"] = header
        checked["path"] = path
        return checked
    except EncryptedBackupError as exc:
        return {
            "ok": False,
            "status": exc.status,
            "encrypted": True,
            "errors": [str(exc)],
            "manifest": {},
            "path": path,
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "unreadable",
            "encrypted": True,
            "errors": [str(exc)],
            "manifest": {},
            "path": path,
        }


@contextmanager
def materialized(path: str, password: str | None):
    """Yield a verified plain ZIP for an encrypted or legacy backup."""
    if not is_encrypted(path):
        yield path
        return
    if not password:
        raise EncryptedBackupError(
            "A password is required for this encrypted backup.", status="password_required"
        )
    plain_path, _header = decrypt_to_temp(path, password)
    try:
        yield plain_path
    finally:
        try:
            os.unlink(plain_path)
        except OSError:
            pass


def create_encrypted_backup(
    base_dir: str,
    password: str,
    *,
    destination: str | None = None,
    kind: str = "manual",
    now: int | None = None,
) -> backup_service.BackupResult:
    """Build a verified plain archive, encrypt it, verify it, then publish it.

    The intermediate ZIP is placed in a private temporary directory outside the
    profile and removed in ``finally``.  It is never published under the backup
    destination and never appears in the backup list.
    """
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_CHARS:
        return backup_service.BackupResult(
            ok=False,
            error=f"Use a password of at least {MIN_PASSWORD_CHARS} characters.",
        )
    if not _LOCK.acquire(blocking=False):
        return backup_service.BackupResult(ok=False, error="Another encrypted backup is already in progress.")
    temporary_dir = _private_temp_dir("encrypt-")
    try:
        policy = backup_service.load_policy(base_dir)
        target_dir = os.path.abspath(destination or policy.destination)
        if not backup_service.destination_is_separate(base_dir, target_dir):
            return backup_service.BackupResult(
                ok=False, error="The backup destination must be outside the active profile."
            )
        plain = backup_service.create_backup(
            base_dir, destination=temporary_dir, kind=kind, now=now
        )
        if not plain.ok:
            return plain
        final_name = os.path.basename(plain.path)
        if final_name.endswith(backup_service.EXTENSION):
            final_name = final_name[: -len(backup_service.EXTENSION)] + EXTENSION
        final_path = os.path.join(target_dir, final_name)
        part_path = os.path.join(target_dir, "." + final_name + ".part")
        created = int((plain.manifest or {}).get("created_at") or time.time())
        _encrypt_archive(plain.path, part_path, password, created_at=created)
        checked = verify_encrypted(part_path, password)
        if not checked.get("ok"):
            try:
                os.replace(part_path, os.path.join(target_dir, "." + final_name + ".failed"))
            except OSError:
                pass
            return backup_service.BackupResult(
                ok=False,
                error="Encrypted backup verification failed; no completed backup was published.",
                verification=checked,
            )
        _atomic_replace(part_path, final_path)
        _log.info("encrypted backup %s created", final_name)
        return backup_service.BackupResult(
            ok=True,
            path=final_path,
            manifest=checked.get("manifest") or plain.manifest,
            verification=checked,
            encrypted=True,
        )
    except (OSError, ValueError, EncryptedBackupError) as exc:
        return backup_service.BackupResult(ok=False, error=f"Encrypted backup failed: {exc}")
    finally:
        _LOCK.release()
        shutil.rmtree(temporary_dir, ignore_errors=True)


__all__ = [
    "CIPHER",
    "EncryptedBackupError",
    "EXTENSION",
    "FORMAT_VERSION",
    "KDF",
    "MAGIC",
    "MIN_PASSWORD_CHARS",
    "create_encrypted_backup",
    "cleanup_stale_temp",
    "decrypt_to_temp",
    "inspect",
    "is_encrypted",
    "materialized",
    "verify_encrypted",
]
