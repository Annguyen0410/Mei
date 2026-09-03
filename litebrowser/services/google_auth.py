from __future__ import annotations

import json
import time
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEVICE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"
REDIRECT_URI = "http://127.0.0.1:47923/oauth2/callback"


class GoogleAuthError(RuntimeError):
    pass


class GoogleAuthDenied(GoogleAuthError):
    """User denied the sign-in / device code expired / timeout."""


def _json_post(url: str, payload: dict) -> dict:
    body = urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body_txt = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        except Exception:
            body_txt = ""
        detail = body_txt.strip() or str(exc)
        raise GoogleAuthError(f"Google API refused (HTTP {exc.code}). Response: {detail[:600]}") from exc


def _device_code_request(client_id: str) -> dict:
    return _json_post(DEVICE_ENDPOINT, {
        "client_id": client_id,
        "scope": SCOPES,
    })


def _poll_token(client_id: str, device_code: str) -> dict:
    return _json_post(TOKEN_ENDPOINT, {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    })


def refresh_access_token(client_id: str, refresh_token: str) -> dict:
    if not refresh_token:
        raise GoogleAuthError("No refresh token available. Sign in again.")
    data = _json_post(TOKEN_ENDPOINT, {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if "error" in data:
        raise GoogleAuthError(f"Token refresh failed: {data.get('error_description', data['error'])}")
    return data


def ensure_valid_token(client_id: str, cached: dict | None) -> dict | None:
    if not cached:
        return None
    obtained_at = int(cached.get("obtained_at", 0) or 0)
    expires_in = int(cached.get("expires_in", 0) or 0)
    now = int(time.time())
    if obtained_at + expires_in - 60 > now:
        return cached
    refresh = cached.get("refresh_token", "")
    if not refresh:
        return None
    try:
        result = refresh_access_token(client_id, refresh)
        cached["access_token"] = result.get("access_token", cached["access_token"])
        if result.get("refresh_token"):
            cached["refresh_token"] = result["refresh_token"]
        cached["expires_in"] = int(result.get("expires_in", expires_in))
        cached["obtained_at"] = now
        return cached
    except GoogleAuthError:
        return None


def request_device_code(client_id: str) -> dict:
    """Step 1 (fast): ask Google for a device code. Raises GoogleAuthError."""
    device = _device_code_request(client_id)
    user_code = device.get("user_code", "")
    device_code = device.get("device_code", "")
    if not user_code or not device_code:
        raise GoogleAuthError("Failed to get device code from Google.")
    return device


def poll_device_token(client_id: str, device: dict) -> dict:
    """Step 2 (long): poll until the user completes sign-in.

    Runs on a worker thread — no Qt GUI objects may be touched here. Raises
    GoogleAuthDenied for user-facing cancellation outcomes.
    """
    import webbrowser

    verification_url = device.get("verification_url", "https://www.google.com/device")
    device_code = device.get("device_code", "")
    expires_in = int(device.get("expires_in", 1800) or 1800)
    interval = int(device.get("interval", 5) or 5)

    webbrowser.open(verification_url)

    deadline = time.time() + expires_in
    while time.time() < deadline:
        try:
            result = _poll_token(client_id, device_code)
        except GoogleAuthError as e:
            raise GoogleAuthError(str(e)) from e
        error = result.get("error", "")
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval = min(interval + 5, 30)
            time.sleep(interval)
            continue
        if error == "access_denied":
            raise GoogleAuthDenied("Sign-in was denied.")
        if error == "expired_token":
            raise GoogleAuthDenied("Device code expired. Please try again.")
        if result.get("access_token"):
            access_token = result["access_token"]
            profile_req = urllib.request.Request(USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"})
            with urllib.request.urlopen(profile_req, timeout=30) as resp:
                profile = json.loads(resp.read().decode("utf-8"))
            now = int(time.time())
            return {
                "account": {
                    "sub": profile.get("sub", ""),
                    "email": profile.get("email", ""),
                    "email_verified": bool(profile.get("email_verified", False)),
                    "name": profile.get("name", ""),
                    "picture": profile.get("picture", ""),
                    "given_name": profile.get("given_name", ""),
                    "family_name": profile.get("family_name", ""),
                    "updated_at": now,
                },
                "tokens": {
                    "access_token": result.get("access_token", ""),
                    "refresh_token": result.get("refresh_token", ""),
                    "id_token": result.get("id_token", ""),
                    "scope": result.get("scope", ""),
                    "token_type": result.get("token_type", ""),
                    "expires_in": int(result.get("expires_in", 0) or 0),
                    "obtained_at": now,
                },
            }
    raise GoogleAuthDenied("Sign-in timed out. Please try again.")


def sign_in_via_device_code(client_id: str, parent_widget=None) -> dict | None:
    """Backward-compatible combined flow (blocking, no GUI calls)."""
    device = request_device_code(client_id)
    return poll_device_token(client_id, device)
