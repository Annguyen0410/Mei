# Mei - Tracking/Ad blocker + HTTPS-only
import os
import re

from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor

_CACHED_CHROME_VERSION: str | None = None
_CACHED_CHROME_FULL_VERSION: str | None = None
_DOMAIN_RE = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def _detect_chrome_versions():
    """Return ``(major, full)`` Chrome version reported by the Qt WebEngine build.

    Both values are cached after the first successful call because this runs on
    every HTTP request via ``interceptRequest`` — repeatedly creating /
    querying a default ``QWebEngineProfile`` is both expensive and (when called
    before a QApplication exists) unstable on Windows. The probe falls back to
    a sensible Chrome 122 default until the real Qt application is up.
    """
    global _CACHED_CHROME_VERSION, _CACHED_CHROME_FULL_VERSION
    if _CACHED_CHROME_VERSION is not None and _CACHED_CHROME_FULL_VERSION is not None:
        return _CACHED_CHROME_VERSION, _CACHED_CHROME_FULL_VERSION
    major = _CACHED_CHROME_VERSION or "122"
    full = _CACHED_CHROME_FULL_VERSION or "122.0.6261.171"
    try:
        from PyQt5.QtWidgets import QApplication
        if QApplication.instance() is None:
            return major, full
        from PyQt5.QtWebEngineWidgets import QWebEngineProfile
        ua = QWebEngineProfile.defaultProfile().httpUserAgent() or ""
        import re
        m_full = re.search(r"Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)", ua)
        if m_full:
            major = m_full.group(1)
            full = ".".join(m_full.groups())
        else:
            m = re.search(r"Chrome/(\d+)", ua)
            if m:
                major = m.group(1)
                full = f"{major}.0.0.0"
    except Exception:
        pass
    _CACHED_CHROME_VERSION = major
    _CACHED_CHROME_FULL_VERSION = full
    return major, full


def _detect_chrome_version():
    """Backwards-compatible helper: return only the major Chrome version."""
    return _detect_chrome_versions()[0]


def _modern_google_ua():
    ver = _detect_chrome_version()
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{ver}.0.0.0 Safari/537.36"
    )


def _trusted_challenge_domains():
    return (
        "challenges.cloudflare.com",
        "cloudflare.com",
        "hcaptcha.com",
        "newassets.hcaptcha.com",
        "js.hcaptcha.com",
        "arkoselabs.com",
        "funcaptcha.com",
    )


def _default_blocked_domains():
    return [
        # Analytics / tag managers / trackers
        "google-analytics.com", "googletagmanager.com", "googletagservices.com",
        "googleadservices.com", "googleads.com", "googlesyndication.com",
        "doubleclick.net", "adsense.com", "2mdn.net", "adservice.google.com",
        "facebook.net", "connect.facebook.net", "pixel.facebook.com",
        "analytics.tiktok.com", "analytics.twitter.com",
        "hotjar.com", "clarity.ms", "scorecardresearch.com", "quantserve.com",
        "criteo.com", "criteo.net", "outbrain.com", "taboola.com", "adsystem.com",
        "adroll.com", "adnxs.com", "rubiconproject.com", "amazon-adsystem.com",
        "aaxads.com", "aax.amazon-adsystem.com", "advertising.amazon.com",
        "adskeeper.com", "mgid.com", "popads.net", "popcash.net", "exo-click.com",
        "propellerads.com", "bidvertiser.com", "media.net",
        "smartadserver.com", "adform.net", "adsrvr.org", "demdex.net", "everesttech.net",
        "bluekai.com", "krxd.net", "segment.io", "segment.com", "mixpanel.com",
        "amplitude.com", "fullstory.com", "mouseflow.com", "luckyorange.com",
        "crazyegg.com", "inspectlet.com",
        # Ad exchanges / SSP / networks
        "pubmatic.com", "openx.net", "indexww.com", "casalemedia.com",
        "yieldmo.com", "sonobi.com", "sharethrough.com", "districtm.io",
        "districtm.ca", "triplelift.com", "gumgum.com", "33across.com",
        "teads.tv", "sovrn.com", "zedo.com", "revcontent.com", "content.ad",
        "infolinks.com", "mediavine.com", "adthrive.com", "ezoic.net", "ezoic.com",
        "moatads.com", "serving-sys.com", "advertising.com", "adzerk.net",
        "skimresources.com", "skimlinks.com", "viglink.com", "awin1.com",
        "linksynergy.com", "shopstyle.com", "rakutenadvertising.com",
        # Mobile attribution / tracking SDKs
        "branch.io", "appsflyer.com", "adjust.com", "kochava.com",
    ]


_COMPAT_DOMAINS = (
    "google.com",
    "googleapis.com",
    "googleusercontent.com",
    "gstatic.com",
    "googlevideo.com",
    "google.co",
    "accounts.google.com",
    "accounts.google.co",
    "myaccount.google.com",
    "accounts.youtube.com",
    "ssl.gstatic.com",
    "lh3.googleusercontent.com",
    "play.google.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "openai.com",
    "claude.ai",
    "anthropic.com",
    "copilot.microsoft.com",
    "bing.com",
    "microsoft.com",
    "perplexity.ai",
)


def _is_compat_domain(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _COMPAT_DOMAINS)


def load_domains_from_filter_file(path):
    """Parse filter file for ||domain^ or plain domain lines; return set of domain substrings to block."""
    domains = set()
    if not path or not os.path.isfile(path):
        return domains
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("!") or line.startswith("["):
                    continue
                if line.startswith("||") and "^" in line:
                    domain = line[2:].split("^")[0].strip()
                    if _DOMAIN_RE.fullmatch(domain):
                        domains.add(domain)
                elif line.startswith("||"):
                    domain = line[2:].strip()
                    if _DOMAIN_RE.fullmatch(domain):
                        domains.add(domain)
                elif "^" in line:
                    domain = line.split("^")[0].strip()
                    if _DOMAIN_RE.fullmatch(domain):
                        domains.add(domain)
    except Exception:
        pass
    return domains


def fetch_and_update_subscriptions(base_dir):
    """Download subscribed filter lists, merge into a local cached file."""
    try:
        from litebrowser.core import prefs
        subs = prefs.get_adblock_subscriptions(base_dir)
        if not subs:
            return
        import urllib.request
        merged = []
        cached_dir = os.path.join(base_dir, "adblock_cache")
        os.makedirs(cached_dir, exist_ok=True)
        for sub in subs:
            url = sub.get("url", "")
            name = sub.get("name", "unknown")
            if not url:
                continue
            cache_path = os.path.join(cached_dir, f"{name}.txt")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mei/3.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read().decode("utf-8", errors="replace")
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write(data)
            except Exception:
                if os.path.isfile(cache_path):
                    with open(cache_path, "r", encoding="utf-8", errors="replace") as f:
                        data = f.read()
                else:
                    continue
            for line in data.splitlines():
                line = line.strip()
                if not line or line.startswith("!") or line.startswith("["):
                    continue
                merged.append(line)
        if merged:
            merged_path = os.path.join(cached_dir, "_merged.txt")
            with open(merged_path, "w", encoding="utf-8") as f:
                f.write("\n".join(merged))
            prefs.set_adblock_filter_file(base_dir, merged_path)
    except Exception:
        pass


class TrackingBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent=None, base_dir=None):
        super().__init__(parent)
        self._base_dir = base_dir
        self.https_only = False
        self.strict_referrer = True
        self.strip_client_hints = True
        self._blocked_domains = frozenset(_default_blocked_domains())
        self._filter_file_domains = set()
        self._all_blocked_domains = self._blocked_domains
        if base_dir:
            self.reload_filter_file()
            self._reload_privacy_prefs()

    def reload_filter_file(self):
        if not self._base_dir:
            return
        try:
            from litebrowser.core import prefs
            path = prefs.get_adblock_filter_file(self._base_dir)
            self._filter_file_domains = load_domains_from_filter_file(path)
        except Exception:
            self._filter_file_domains = set()
        self._all_blocked_domains = self._blocked_domains | frozenset(self._filter_file_domains)

    def _reload_privacy_prefs(self):
        if not self._base_dir:
            return
        try:
            from litebrowser.core import prefs
            self.strict_referrer = bool(prefs.get_strict_referrer(self._base_dir))
            self.strip_client_hints = bool(prefs.get_strip_client_hints(self._base_dir))
        except Exception:
            pass

    def _all_blocked(self):
        return self._all_blocked_domains

    def _is_trusted_challenge_url(self, host: str) -> bool:
        host = (host or "").lower().rstrip(".")
        return any(host == domain or host.endswith("." + domain) for domain in _trusted_challenge_domains())

    def _is_blocked_host(self, host: str) -> bool:
        """O(labels) suffix lookup instead of a linear scan over the block list."""
        blocked = self._all_blocked_domains
        if not blocked:
            return False
        host = (host or "").lower().rstrip(".")
        if not host:
            return False
        if host in blocked:
            return True
        labels = host.split(".")
        for i in range(1, len(labels)):
            parent = ".".join(labels[i:])
            if parent in blocked:
                return True
        return False

    def interceptRequest(self, info):
        url_str = info.requestUrl().toString()
        host = info.requestUrl().host().lower()
        is_compat = _is_compat_domain(host)
        is_challenge = self._is_trusted_challenge_url(host)
        if is_compat:
            # Google Gaia (and friends) refuse sign-in when requests don't carry the
            # Client Hints headers that real Chrome sends. Qt WebEngine 6.8 has
            # Chromium ~122 which *does* support Client Hints, but does not emit
            # Sec-CH-UA on every nav by default. Inject a consistent Chrome 122
            # / Windows fingerprint here; this is the single biggest factor in
            # the "This browser or app may not be secure" block.
            #
            # full_ver is read from the live QWebEngineProfile UA so the
            # spoofed Sec-CH-UA-Full-Version matches the actual Qt Chromium
            # build (e.g. 122.0.6261.171, not a hard-coded 122.0.6261.112).
            ver, full_ver = _detect_chrome_versions()
            sec_ch_ua = (
                f'"Chromium";v="{ver}", "Not(A:Brand";v="24", "Google Chrome";v="{ver}"'
            ).encode("ascii")
            info.setHttpHeader(b"sec-ch-ua", sec_ch_ua)
            info.setHttpHeader(b"sec-ch-ua-mobile", b"?0")
            info.setHttpHeader(b"sec-ch-ua-platform", b'"Windows"')
            info.setHttpHeader(b"sec-ch-ua-platform-version", b'"15.0.0"')
            info.setHttpHeader(b"sec-ch-ua-arch", b'"x86"')
            info.setHttpHeader(b"sec-ch-ua-bitness", b'"64"')
            info.setHttpHeader(b"sec-ch-ua-model", b'""')
            info.setHttpHeader(b"sec-ch-ua-full-version", f'"{full_ver}"'.encode("ascii"))
            info.setHttpHeader(
                b"sec-ch-ua-full-version-list",
                (
                    f'"Chromium";v="{full_ver}", '
                    f'"Not(A:Brand";v="24.0.0.0", '
                    f'"Google Chrome";v="{full_ver}"'
                ).encode("ascii"),
            )
        if not is_challenge:
            info.setHttpHeader(b"DNT", b"1")
            info.setHttpHeader(b"Sec-GPC", b"1")
            # Referrer-Policy is intentionally NOT set as a request header here.
            # Doing so would trigger CORS preflights on cross-origin requests
            # because referrer-policy is not CORS-safelisted and Google et al.
            # don't include it in Access-Control-Allow-Headers.
            # Qt WebEngine (Chromium ~122) already enforces
            # strict-origin-when-cross-origin by default.
            if self.strip_client_hints and not is_compat:
                # These headers leak OS / CPU / GPU details to every site.
                # Compatibility hosts above already got their own values; for
                # everyone else we strip them entirely.
                for h in (
                    b"sec-ch-ua-platform-version",
                    b"sec-ch-ua-arch",
                    b"sec-ch-ua-bitness",
                    b"sec-ch-ua-model",
                    b"sec-ch-ua-full-version",
                    b"sec-ch-ua-full-version-list",
                    b"sec-ch-ua-wow64",
                ):
                    info.setHttpHeader(h, b"")

        if self.https_only:
            if url_str.startswith("http://"):
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url_str)
                    hostname = (parsed.hostname or "").lower()
                except Exception:
                    hostname = ""
                if hostname and hostname not in ("localhost", "127.0.0.1", "::1"):
                    # Upgrade to https instead of blocking dead (v6.4 served a
                    # bare ERR page; Chrome-style auto-upgrade keeps the page
                    # working when the site supports TLS).
                    info.redirect(QUrl("https://" + url_str[len("http://"):]))
                    return

        if is_challenge:
            return
        if self._is_blocked_host(host):
            info.block(True)
            return
