"""What Mei's browser engine actually is, and how it says so.

Mei used to answer this question by pretending to be Google Chrome: a
DocumentCreation script deleted ``navigator.webdriver``, replaced
``navigator.plugins`` with a fake PDF list, invented a ``deviceMemory`` of 8,
rewrote WebGL's unmasked GPU strings and shaped ``navigator.userAgentData``
with a "Google Chrome" brand. That ran on *every* page, in the main world and
in every subframe, so every website Mei visited received a fabricated
fingerprint — including sites that were not sign-in providers and had no
compatibility problem at all.

That is not a compatibility fix. It is fingerprint spoofing: it hides the fact
that this is an embedded browser from anti-bot systems, contradicts what the
engine really reports, and is unreliable by construction (a spoofed value that
disagrees with a native one is itself a detection signal).

This module replaces it with a *truthful* identity:

* the user agent names the product (``Mei/<version>``) and the Chromium build
  the engine really is — it never claims to be Google Chrome;
* no JavaScript API is patched globally; ``navigator.*``, WebGL and
  ``window.chrome`` are whatever the engine actually provides;
* the only compatibility work left is a set of HTTP Client Hints sent to the
  handful of *sign-in* origins that refuse embedded engines without them. It is
  network-layer, opt-in, origin-scoped, and reports the real Chromium version.

Sites that still refuse an embedded engine get a clear notice and can be opened
in the user's default browser (see ``MainWindow.open_in_external_browser``)
instead of being lied to.
"""

from __future__ import annotations

import re

from litebrowser.core import product

#: Origins where a *sign-in* flow is known to require Client Hints that a plain
#: Qt WebEngine request does not send. Deliberately narrow: adding a domain here
#: means "this origin's login breaks without browser hints", not "make this site
#: look like Chrome". Ordinary browsing never matches.
SIGN_IN_COMPAT_HOSTS: tuple[str, ...] = (
    "accounts.google.com",
    "accounts.youtube.com",
    "gemini.google.com",
    "chatgpt.com",
    "auth.openai.com",
    "claude.ai",
    "login.microsoftonline.com",
    "copilot.microsoft.com",
    "perplexity.ai",
)

#: A UA token keeps the engine's real Chromium version but names Mei. It must
#: never contain "QtWebEngine" (many CDNs serve it an unsupported-browser page)
#: and must never contain "Google Chrome" (that would be the claim this module
#: exists to remove).
_UA_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Mei/{mei} Chrome/{major}.0.0.0 Safari/537.36"
)

_CHROME_RE = re.compile(r"Chrome/(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?")


def chromium_version(profile=None) -> tuple[str, str]:
    """Return ``(major, full)`` for the running Chromium, or ``("", "")``.

    The binding is authoritative: Qt 6.11's default user agent only says
    ``Chrome/140.0.0.0``, while ``qWebEngineChromiumVersion()`` knows the real
    patch build. PyQt5 has no such function, so the UA is the fallback there.
    An unknown version is returned as unknown — never guessed.
    """
    raw = ""
    try:  # through the project facade, never the binding directly
        from litebrowser.qt import QtWebEngineCore

        ask = getattr(QtWebEngineCore, "qWebEngineChromiumVersion", None)
        if callable(ask):
            raw = str(ask() or "").strip()
    except Exception:
        raw = ""
    if raw:
        parts = raw.split(".")
        if len(parts) >= 2 and parts[0].isdigit():
            return parts[0], ".".join(parts[:4])
    if profile is not None:
        try:
            user_agent = str(profile.httpUserAgent() or "")
        except Exception:
            user_agent = ""
        match = _CHROME_RE.search(user_agent)
        if match:
            groups = [group for group in match.groups() if group]
            return groups[0], ".".join(groups)
    return "", ""


def build_user_agent(profile=None, mei_version: str = "") -> str:
    """The UA Mei sends: real Chromium version, honest product name.

    With no readable Chromium version the ``Chrome/`` token is omitted rather
    than invented, so the header never states a build the engine is not.
    """
    major, _full = chromium_version(profile)
    mei = str(mei_version or product.APP_VERSION).strip() or product.APP_VERSION
    if not major:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Mei/{mei} Safari/537.36"
        )
    return _UA_TEMPLATE.format(mei=mei, major=major)


def is_sign_in_host(host: str) -> bool:
    """True only for an allowlisted sign-in origin (or a subdomain of one)."""
    value = str(host or "").strip().lower().rstrip(".")
    if not value:
        return False
    return any(value == item or value.endswith("." + item) for item in SIGN_IN_COMPAT_HOSTS)


def client_hint_headers(chromium_major: str, chromium_full: str, mei_version: str = "") -> dict[bytes, bytes]:
    """Client Hints describing this engine, not a Google Chrome install.

    Brand list says Chromium plus Mei. ``sec-ch-ua`` is what a Chromium-based
    product is supposed to send; claiming the ``Google Chrome`` brand is the
    impersonation this module removes. Values are derived from the real engine
    so they cannot contradict each other.
    """
    major = str(chromium_major or "").strip()
    full = str(chromium_full or "").strip()
    if not major:
        return {}
    if not full or not full.startswith(major + "."):
        full = f"{major}.0.0.0"
    mei = str(mei_version or product.APP_VERSION).strip() or product.APP_VERSION
    brand_list = f'"Chromium";v="{major}", "Mei";v="{mei}", "Not(A:Brand";v="24"'
    full_list = f'"Chromium";v="{full}", "Mei";v="{mei}", "Not(A:Brand";v="24.0.0.0"'
    return {
        b"sec-ch-ua": brand_list.encode("ascii", "ignore"),
        b"sec-ch-ua-mobile": b"?0",
        b"sec-ch-ua-platform": b'"Windows"',
        b"sec-ch-ua-arch": b'"x86"',
        b"sec-ch-ua-bitness": b'"64"',
        b"sec-ch-ua-model": b'""',
        b"sec-ch-ua-full-version": f'"{full}"'.encode("ascii", "ignore"),
        b"sec-ch-ua-full-version-list": full_list.encode("ascii", "ignore"),
    }


__all__ = [
    "SIGN_IN_COMPAT_HOSTS",
    "build_user_agent",
    "chromium_version",
    "client_hint_headers",
    "is_sign_in_host",
]
