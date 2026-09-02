# Mei - Password manager (basic): encrypted store + autofill
import base64
import hashlib
import json
import os

from litebrowser.core.profile_lock import profile_locked

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


_VAULT_VERSION = 2
_KDF_NAME = "pbkdf2-sha256"
_KDF_ITERATIONS = 390000
_SALT_BYTES = 16


def _derive_key(master_password):
    """Legacy static derivation kept so existing password vaults can be read."""
    if not master_password:
        return None
    key = hashlib.sha256(("litebrowser_pw_salt_" + master_password).encode()).digest()
    return base64.urlsafe_b64encode(key).decode()


def _derive_pbkdf2_key(master_password, salt, iterations):
    if not master_password or not salt:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=int(iterations or _KDF_ITERATIONS),
        backend=default_backend(),
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def _get_cipher(master_password):
    """Legacy cipher kept for read compatibility with pre-v2 vault files."""
    if not HAS_CRYPTO or not master_password:
        return None
    try:
        key = _derive_key(master_password)
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def _passwords_path(base_dir):
    return os.path.join(base_dir, "SafeVault", "passwords.enc")


def _get_v2_cipher(master_password, salt=None, iterations=_KDF_ITERATIONS):
    if not HAS_CRYPTO or not master_password:
        return None, None
    try:
        salt = salt or os.urandom(_SALT_BYTES)
        key = _derive_pbkdf2_key(master_password, salt, iterations)
        if not key:
            return None, None
        return Fernet(key), salt
    except Exception:
        return None, None


def _encrypted_entry(entry, cipher):
    item = {"url": entry.get("url", ""), "username": entry.get("username", "")}
    pw = entry.get("password") or entry.get("password_plain", "")
    if pw:
        item["password"] = cipher.encrypt(str(pw).encode("utf-8")).decode("utf-8")
    else:
        item["password"] = entry.get("password_encrypted", "")
    return item


def _decrypt_entries(data, cipher):
    out = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        pw = entry.get("password", "")
        if pw:
            try:
                token = pw.encode("utf-8") if isinstance(pw, str) else pw
                pw = cipher.decrypt(token).decode("utf-8")
            except Exception:
                # Decryption failed: surface an empty password instead of the
                # ciphertext blob (v6.4 leaked the encrypted string as if it
                # were the plaintext password into the UI and autofill).
                pw = ""
        out.append({"url": entry.get("url", ""), "username": entry.get("username", ""), "password": pw})
    return out


def _encode_v2_vault(entries, master_password):
    cipher, salt = _get_v2_cipher(master_password)
    if not cipher or not salt:
        return None
    payload = [_encrypted_entry(entry, cipher) for entry in entries]
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    envelope = {
        "version": _VAULT_VERSION,
        "kdf": {
            "name": _KDF_NAME,
            "iterations": _KDF_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
        },
        "payload": cipher.encrypt(raw).decode("utf-8"),
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")


def _decode_v2_vault(blob, master_password):
    """Returns (handled, entries). handled=False means 'not a v2 vault';

    handled=True with entries=list (possibly empty) means decrypted OK;
    handled=True with entries=None means the vault IS v2 but could NOT be
    decrypted (wrong password / corrupt). Callers must never overwrite the
    vault in that case (v6.4 wiped the whole vault on a typo'd password)."""
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except Exception:
        return False, []
    if not isinstance(envelope, dict):
        return False, []
    try:
        version = int(envelope.get("version", 0) or 0)
    except (TypeError, ValueError):
        return False, []
    if version != _VAULT_VERSION:
        return False, []
    try:
        kdf = envelope.get("kdf") if isinstance(envelope.get("kdf"), dict) else {}
        if kdf.get("name") != _KDF_NAME:
            return True, None
        salt = base64.b64decode(kdf.get("salt") or "")
        iterations = int(kdf.get("iterations") or _KDF_ITERATIONS)
        cipher, _ = _get_v2_cipher(master_password, salt=salt, iterations=iterations)
        if not cipher:
            return True, None
        raw = cipher.decrypt(str(envelope.get("payload") or "").encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return True, _decrypt_entries(data, cipher)
    except Exception:
        return True, None


class VaultUnlockError(RuntimeError):
    """Raised when a v2 vault exists but the master password is wrong."""


def save_passwords(base_dir, entries, master_password):
    """entries: list of {url_pattern, username, password_encrypted or plain}. Encrypts and writes."""
    if not HAS_CRYPTO or not master_password:
        return False
    encoded = _encode_v2_vault(entries if isinstance(entries, list) else [], master_password)
    if not encoded:
        return False
    try:
        path = _passwords_path(base_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with profile_locked(base_dir):
            with open(tmp_path, "wb") as f:
                f.write(encoded)
            os.replace(tmp_path, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def load_passwords(base_dir, master_password):
    """Returns list of {url, username, password} (decrypted)."""
    status, entries = load_passwords_status(base_dir, master_password)
    return entries


def load_passwords_status(base_dir, master_password):
    """Returns (status, entries); status is one of:
    - "ok":      vault read and decrypted (may be empty)
    - "missing": no vault file yet
    - "locked":  a vault exists but the master password is wrong / file corrupt
    """
    if not HAS_CRYPTO or not master_password:
        return "missing", []
    cipher = _get_cipher(master_password)
    if not cipher:
        return "missing", []
    path = _passwords_path(base_dir)
    if not os.path.isfile(path):
        return "missing", []
    try:
        with profile_locked(base_dir), open(path, "rb") as f:
            blob = f.read()
        handled, entries = _decode_v2_vault(blob, master_password)
        if handled:
            return ("locked" if entries is None else "ok"), (entries or [])
        raw = cipher.decrypt(blob).decode("utf-8")
        data = json.loads(raw)
        return "ok", _decrypt_entries(data, cipher)
    except Exception:
        return "locked", []


def add_password(base_dir, url, username, password, master_password):
    status, entries = load_passwords_status(base_dir, master_password)
    if status == "locked":
        # The vault exists but this master password cannot decrypt it. Saving
        # now would replace every stored credential with just this one entry —
        # refuse instead (v6.4 silently wiped the whole vault on a typo).
        raise VaultUnlockError(
            "The saved password vault could not be unlocked with this master password. "
            "Nothing was changed. Check the password and try again."
        )
    url_norm = _normalize_origin(url)
    for e in entries:
        if _origin_match(e["url"], url_norm) and e["username"] == username:
            e["password"] = password
            return save_passwords(base_dir, entries, master_password)
    entries.append({"url": url_norm, "username": username, "password": password})
    return save_passwords(base_dir, entries, master_password)


def get_credentials_for(base_dir, url, master_password):
    entries = load_passwords(base_dir, master_password)
    url_norm = _normalize_origin(url)
    for e in entries:
        if _origin_match(e["url"], url_norm):
            return {"username": e["username"], "password": e["password"]}
    return None


def _normalize_origin(url):
    if not url:
        return ""
    url = url.strip()
    for p in ("https://", "http://"):
        if url.startswith(p):
            url = url[len(p):]
            break
    if "/" in url:
        url = url.split("/")[0]
    return url.lower()


def _origin_match(stored_origin, page_origin):
    if not stored_origin or not page_origin:
        return False
    so = stored_origin.lower()
    po = page_origin.lower()
    return po == so or po.endswith("." + so) or so.endswith("." + po)


AUTOFILL_SCRIPT = """
(function() {
  var form = document.querySelector('form');
  if (!form) return;
  var inputs = form.querySelectorAll('input');
  var userInput = null, passInput = null;
  for (var i = 0; i < inputs.length; i++) {
    var n = (inputs[i].name || '').toLowerCase();
    var t = (inputs[i].type || '').toLowerCase();
    if (t === 'password') passInput = inputs[i];
    else if (n.indexOf('user') >= 0 || n.indexOf('email') >= 0 || n.indexOf('login') >= 0) userInput = inputs[i];
    else if (t === 'text' && !userInput) userInput = inputs[i];
  }
  if (userInput && passInput && typeof __lite_username !== 'undefined' && typeof __lite_password !== 'undefined') {
    userInput.value = __lite_username;
    passInput.value = __lite_password;
    userInput.dispatchEvent(new Event('input', { bubbles: true }));
    passInput.dispatchEvent(new Event('input', { bubbles: true }));
  }
})();
"""


def build_autofill_script(username, password):
    """Returns JS string that sets __lite_username/__lite_password and runs AUTOFILL_SCRIPT."""
    u_esc = json.dumps(username)
    p_esc = json.dumps(password)
    return "var __lite_username = " + u_esc + "; var __lite_password = " + p_esc + "; " + AUTOFILL_SCRIPT.strip()
