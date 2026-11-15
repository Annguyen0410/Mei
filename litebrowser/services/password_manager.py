# Mei - Password manager (basic): encrypted store + autofill
import base64
import hashlib
import json
import os
from urllib.parse import urlsplit

from litebrowser.core.log import get_logger
from litebrowser.core.profile_lock import profile_locked, profile_transaction
from litebrowser.core.storage_utils import write_text_atomic

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

_log = get_logger("password_manager")


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
    except Exception as exc:  # noqa: BLE001  crypto failure -> no legacy cipher (never log the password)
        _log.warning("legacy cipher derivation failed: %s", type(exc).__name__)
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
    except Exception as exc:  # noqa: BLE001  crypto failure -> no v2 cipher (never log the password)
        _log.warning("v2 cipher derivation failed: %s", type(exc).__name__)
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
            except Exception as exc:  # noqa: BLE001  bad token -> empty (never log the password)
                _log.warning("entry decrypt failed: %s", type(exc).__name__)
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
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
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
        if not 100_000 <= iterations <= 2_000_000 or len(salt) != _SALT_BYTES:
            return True, None
        cipher, _ = _get_v2_cipher(master_password, salt=salt, iterations=iterations)
        if not cipher:
            return True, None
        raw = cipher.decrypt(str(envelope.get("payload") or "").encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return True, _decrypt_entries(data, cipher)
    except Exception:  # noqa: BLE001  any crypto/decode failure means locked
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
        with profile_locked(base_dir):
            write_text_atomic(_passwords_path(base_dir), encoded.decode("utf-8"))
        return True
    except (OSError, ValueError) as exc:
        _log.warning("password vault save failed: %s", type(exc).__name__)
        return False


def load_passwords(base_dir, master_password):
    """Returns list of {url, username, password} (decrypted)."""
    status, entries = load_passwords_status(base_dir, master_password)
    return entries


def _migrate_legacy_vault(base_dir, entries, master_password):
    """Re-encrypt a legacy (static-key) vault into the PBKDF2 envelope.

    The legacy format derives its Fernet key from a fixed salt and one SHA-256
    round, so a stolen vault file is cheap to attack offline. Reading it stays
    supported, but the first successful unlock rewrites it as v2 instead of
    leaving the weak file on disk for the life of the profile.
    """
    try:
        return bool(save_passwords(base_dir, entries, master_password))
    except Exception as exc:  # noqa: BLE001 - migration never fails the read
        _log.warning("legacy vault migration failed: %s", type(exc).__name__)
        return False


def load_passwords_status(base_dir, master_password, _migrate=True):
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
        entries = _decrypt_entries(data, cipher)
    except Exception:  # noqa: BLE001  wrong password/corrupt vault must stay locked
        return "locked", []
    # Legacy format reached: rewrite it as v2. Done after the read lock is
    # released, and skipped by callers that are about to save anyway.
    if _migrate:
        _migrate_legacy_vault(base_dir, entries, master_password)
    return "ok", entries


@profile_transaction
def add_password(base_dir, url, username, password, master_password):
    # _migrate=False: this call is already inside a profile transaction and
    # saves the vault below, so re-encrypting on read would be a redundant write
    # from inside the caller's lock.
    status, entries = load_passwords_status(base_dir, master_password, _migrate=False)
    if status == "locked":
        # The vault exists but this master password cannot decrypt it. Saving
        # now would replace every stored credential with just this one entry —
        # refuse instead (v6.4 silently wiped the whole vault on a typo).
        raise VaultUnlockError(
            "The saved password vault could not be unlocked with this master password. "
            "Nothing was changed. Check the password and try again."
        )
    url_norm = _normalize_origin(url)
    if not url_norm:
        return False
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
    try:
        parsed = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return ""
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port
        default = 443 if parsed.scheme == "https" else 80
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != default:
            authority = f"{authority}:{port}"
        return f"{parsed.scheme.lower()}://{authority}"
    except (ValueError, TypeError, AttributeError):
        return ""


def _origin_match(stored_origin, page_origin):
    if not stored_origin or not page_origin:
        return False
    # Old vaults stored host-only entries. Interpret these as HTTPS rather
    # than releasing their secrets on an HTTP downgrade.
    so = _normalize_origin(stored_origin)
    po = _normalize_origin(page_origin)
    return bool(so and po and po == so)


#: Hosts that mean "this machine": a cleartext origin is acceptable there and
#: nowhere else (a dev server on loopback is not on a network path).
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def autofill_allowed(url):
    """True when credentials may be placed into ``url``'s page at all.

    Autofill is a credential boundary of its own: once the value is in a form,
    every script on that page can read it. Two rules follow from that.

    * The origin must be exactly the one the entry was saved for. That is
      enforced separately by ``_origin_match``; this function only screens the
      page origin itself.    * A plaintext ``http`` origin is refused unless it is loopback. A password
      filled into a cleartext page (or cleartext form action) is readable on the
      wire, so the exact-origin match is not by itself enough.

    The form itself is screened by ``AUTOFILL_SCRIPT``: only a POST form on the
    same origin is filled, because a GET submission would put the password in
    the URL (history, Referer, server logs).
    """
    origin = _normalize_origin(url)
    if not origin:
        return False
    parsed = urlsplit(origin)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and (parsed.hostname or "").lower() in _LOOPBACK_HOSTS


def same_origin(url_a, url_b):
    """True when both URLs normalise to one http(s) origin.

    Used to re-validate an armed autofill offer against the document actually in
    front of the user: a redirect between the offer and the keypress must not
    receive the secret.
    """
    a = _normalize_origin(url_a)
    b = _normalize_origin(url_b)
    return bool(a and b and a == b)


def credentials_for_autofill(base_dir, url, master_password):
    """Credentials to fill, or None when this page must not be autofilled."""
    if not autofill_allowed(url):
        return None
    return get_credentials_for(base_dir, url, master_password)


AUTOFILL_SCRIPT = """
(function() {
  // Autofill writes a secret into a document, so the document has to prove it
  // is the one that was matched. A subframe, or a page that navigated between
  // loadFinished and this call, gets nothing.
  if (window.top !== window.self) return;
  if (location.origin !== __lite_expected_origin) return;

  var forms = document.querySelectorAll('form');
  var form = null;
  for (var f = 0; f < forms.length; f++) {
    if (forms[f].querySelector('input[type="password"]')) { form = forms[f]; break; }
  }
  if (!form) return;

  // A form that posts somewhere else would hand the filled password to a
  // different origin, so it is left alone even on the matched origin.
  var action = form.getAttribute('action');
  if (action) {
    var target = null;
    try { target = new URL(action, location.href); } catch (e) { return; }
    if (target.origin !== location.origin) return;
  }

  // A form submitted with GET serialises every field into the URL, so a filled
  // password would land in browser history, in the Referer of the page's next
  // requests and in the server's access log. `form.method` already resolves to
  // the spec default ("get") when the attribute is missing, so an unlabelled
  // form is refused instead of being assumed to be a POST.
  var method = (form.getAttribute('method') || form.method || 'get').toLowerCase();
  if (method !== 'post') return;

  // A submit button can override the form's method; an override that is not
  // POST moves the same secret into the URL.
  var overrides = form.querySelectorAll('button[formmethod], input[formmethod]');
  for (var b = 0; b < overrides.length; b++) {
    if ((overrides[b].getAttribute('formmethod') || '').toLowerCase() !== 'post') return;
  }

  var inputs = form.querySelectorAll('input');
  var userInput = null, passInput = null;
  for (var i = 0; i < inputs.length; i++) {
    var n = (inputs[i].name || '').toLowerCase();
    var t = (inputs[i].type || '').toLowerCase();
    if (t === 'password') { if (!passInput) passInput = inputs[i]; }
    else if (n.indexOf('user') >= 0 || n.indexOf('email') >= 0 || n.indexOf('login') >= 0) { if (!userInput) userInput = inputs[i]; }
    else if (t === 'text' && !userInput) userInput = inputs[i];
  }
  if (!userInput || !passInput || userInput === passInput) return;
  if (typeof __lite_username === 'undefined' || typeof __lite_password === 'undefined') return;

  userInput.value = __lite_username;
  passInput.value = __lite_password;
  userInput.dispatchEvent(new Event('input', { bubbles: true }));
  passInput.dispatchEvent(new Event('input', { bubbles: true }));
  // The values stay in the form (the page needs them to submit); the copies
  // this script carried are dropped with the closure.
})();
"""


def build_autofill_script(username, password, origin=""):
    """Build the autofill JS for one document.

    ``origin`` must be the normalised origin of the page being filled — the
    script refuses to write anything when ``location.origin`` differs, so a
    caller that passes nothing (or a stale URL) gets a no-op instead of a
    credential leak into whatever document is loaded by the time this runs.
    """
    u_esc = json.dumps(username)
    p_esc = json.dumps(password)
    o_esc = json.dumps(_normalize_origin(origin))
    return (
        "(function(){var __lite_expected_origin = "
        + o_esc
        + "; var __lite_username = "
        + u_esc
        + "; var __lite_password = "
        + p_esc
        + "; "
        + AUTOFILL_SCRIPT.strip()
        + "})();"
    )

# Save-password capture was removed in the 2026 overhaul. The old
# DocumentCreation script ran in the page's MAIN world and stored submitted
# credentials as plaintext in ``sessionStorage``, where any script on the
# page could read them. Qt WebEngine has no browser-internal password
# manager and no page->native channel that survives a navigation, so the
# feature is suspended until an isolated-world bridge exists
# (see .ai/decisions/ADR-0006). Autofill and Vault entries are unaffected.
