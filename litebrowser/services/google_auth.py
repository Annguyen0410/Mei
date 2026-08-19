from __future__ import annotations

import json
import time
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode

from PyQt5.QtWidgets import QMessageBox

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEVICE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"
REDIRECT_URI = "http://127.0.0.1:47923/oauth2/callback"


class GoogleAuthError(RuntimeError):
    pass


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


def sign_in_via_device_code(client_id: str, parent_widget=None) -> dict | None:
    import webbrowser

    try:
        device = _device_code_request(client_id)
    except GoogleAuthError as e:
        QMessageBox.critical(parent_widget, "Google OAuth Error", str(e))
        return None

    user_code = device.get("user_code", "")
    verification_url = device.get("verification_url", "https://www.google.com/device")
    device_code = device.get("device_code", "")
    expires_in = int(device.get("expires_in", 1800) or 1800)
    interval = int(device.get("interval", 5) or 5)

    if not user_code or not device_code:
        QMessageBox.critical(parent_widget, "Google OAuth Error", "Failed to get device code from Google.")
        return None

    msg = (
        "Google Sign-In — Device Code\n\n"
        "Step 1: Open this URL in any browser (Chrome, Edge, phone):\n"
        f"    {verification_url}\n\n"
        "Step 2: Enter this code when prompted:\n"
        f"    {user_code}\n\n"
        "Step 3: Sign in to your Google account.\n\n"
        "This window will detect when you've completed sign-in.\n"
        f"Code expires in {expires_in // 60} minutes."
    )
    QMessageBox.information(parent_widget, "Google Sign-In", msg)

    webbrowser.open(verification_url)

    deadline = time.time() + expires_in
    while time.time() < deadline:
        try:
            result = _poll_token(client_id, device_code)
        except GoogleAuthError as e:
            QMessageBox.critical(parent_widget, "Google OAuth Error", str(e))
            return None
        error = result.get("error", "")
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval = min(interval + 5, 30)
            time.sleep(interval)
            continue
        if error == "access_denied":
            QMessageBox.warning(parent_widget, "Google Sign-In", "Sign-in was denied.")
            return None
        if error == "expired_token":
            QMessageBox.warning(parent_widget, "Google Sign-In", "Device code expired. Please try again.")
            return None
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
    QMessageBox.warning(parent_widget, "Google Sign-In", "Sign-in timed out. Please try again.")
    return None
