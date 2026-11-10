# Mei - Tracking/Ad blocker + HTTPS-only
import hashlib
import os
import re
import tempfile
import threading

from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor

from litebrowser.core import app_version
from litebrowser.core.log import get_logger
from litebrowser.services import focus_service, safe_http

_log = get_logger("adblock")

# Distraction Shield defaults: the loud corners of the internet. Custom hosts
# join these via prefs (shield_custom_hosts).
_DISTRACTION_HOSTS = (
    "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com",
    "reddit.com", "9gag.com", "netflix.com", "web.whatsapp.com", "messenger.com",
)

_CACHED_CHROME_VERSION: str | None = None
_CACHED_CHROME_FULL_VERSION: str | None = None
# Only reachable before the engine can answer at all (no Qt yet). A plausible
# major beats an empty client-hint header.
_FALLBACK_CHROME_MAJOR = "122"
_FALLBACK_CHROME_FULL = "122.0.6261.171"
_FULL_CHROME_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_DOMAIN_RE = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def _engine_chrome_versions():
    """``(major, full)`` straight from the binding, or ``("", "")``.

    No QApplication needed, so this is the first thing the probe tries.
    """
    try:
        from PyQt5.QtWebEngineCore import qWebEngineChromiumVersion

        full = (qWebEngineChromiumVersion() or "").strip()
    except Exception:
        return "", ""
    if _FULL_CHROME_VERSION_RE.match(full):
        return full.split(".")[0], full
    return "", ""


def _ua_chrome_versions(user_agent: str):
    """``(major, full)`` read out of a user-agent string, or ``("", "")``.

    Pure text in, text out — no Qt — so the fallback rules stay testable, and so
    the trap is on the record: Qt 6.8's UA carries a real build
    (``Chrome/122.0.6261.171``) while Qt 6.11's says only ``Chrome/140.0.0.0``,
    which matches this shape and would be sent as a build that never existed.
    That is why the binding is asked first and this is only reached without it.
    """
    ua = user_agent or ""
    m_full = re.search(r"Chrome/(\d+)\.(\d+)\.(\d+)\.(\d+)", ua)
    if m_full:
        return m_full.group(1), ".".join(m_full.groups())
    m_major = re.search(r"Chrome/(\d+)", ua)
    if m_major:
        return m_major.group(1), f"{m_major.group(1)}.0.0.0"
    return "", ""


def _detect_chrome_versions():
    """Return ``(major, full)`` Chrome version reported by the Qt WebEngine build.

    Both values are cached after the first successful call because this runs on
    every HTTP request via ``interceptRequest`` — repeatedly creating /
    querying a default ``QWebEngineProfile`` is both expensive and (when called
    before a QApplication exists) unstable on Windows.

    The binding is asked first, and the UA is only a fallback: Qt 6.11's default
    UA says just ``Chrome/140.0.0.0``, so a UA-derived "full" version would put a
    build that never existed into ``sec-ch-ua-full-version``, the header the
    Google-shaped compatibility path lives on. On PyQt5 there is no
    ``qWebEngineChromiumVersion()`` at all, so that branch really does read the
    default profile's UA once and cache it.
    """
    global _CACHED_CHROME_VERSION, _CACHED_CHROME_FULL_VERSION
    if _CACHED_CHROME_VERSION is not None and _CACHED_CHROME_FULL_VERSION is not None:
        return _CACHED_CHROME_VERSION, _CACHED_CHROME_FULL_VERSION
    major, full = _engine_chrome_versions()
    if not full:
        major = _CACHED_CHROME_VERSION or _FALLBACK_CHROME_MAJOR
        full = _CACHED_CHROME_FULL_VERSION or _FALLBACK_CHROME_FULL
        try:
            from PyQt5.QtWidgets import QApplication
            if QApplication.instance() is None:
                return major, full
            from PyQt5.QtWebEngineWidgets import QWebEngineProfile
            ua_major, ua_full = _ua_chrome_versions(QWebEngineProfile.defaultProfile().httpUserAgent())
            if ua_full:
                major, full = ua_major, ua_full
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


def _domain_from_filter_line(line: str) -> str:
    """Extract a blockable domain from one filter line ('||d^', '||d', 'd^').

    Returns '' for comments, blanks and lines without a valid domain."""
    line = line.strip()
    if not line or line.startswith(("!", "[")):
        return ""
    line = line.removeprefix("||")
    if "^" in line:
        line = line.split("^")[0]
    domain = line.strip()
    return domain if _DOMAIN_RE.fullmatch(domain) else ""


MAX_FILTER_FILE_BYTES = 8 * 1024 * 1024
MAX_FILTER_LINES = 200_000
MAX_FILTER_LINE_CHARS = 8192
MAX_MERGED_RULES = 200_000
MAX_SUBSCRIPTIONS = 32

#: One subscription refresh at a time. A second caller gets ``busy`` instead of
#: running duplicate DNS lookups and racing two writers over the same cache.
_SUBSCRIPTION_LOCK = threading.Lock()


def load_domains_from_filter_file(path):
    """Parse ``||domain^`` / bare-domain lines from a bounded filter file.

    Bounds are explicit because the file can come from a subscription: an
    unbounded read is a memory-exhaustion path. Unsupported syntax is skipped
    (see docs/audit/MEI_BROWSER_COMPATIBILITY_MATRIX.md) rather than guessed.
    """
    domains = set()
    if not path or not os.path.isfile(path):
        return domains
    try:
        if os.path.getsize(path) > MAX_FILTER_FILE_BYTES:
            _log.warning("filter file is larger than the parser accepts; ignoring it")
            return domains
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for index, line in enumerate(handle):
                if index >= MAX_FILTER_LINES:
                    _log.warning("filter file exceeds the line limit; truncated")
                    break
                if len(line) > MAX_FILTER_LINE_CHARS:
                    continue
                domain = _domain_from_filter_line(line)
                if domain:
                    domains.add(domain)
    except OSError as exc:
        _log.warning("could not read the filter file (%s)", type(exc).__name__)
    return domains


def _cache_filename(name, url):
    """A safe, stable cache name: sanitized label + URL hash, never raw input."""
    digest = hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip(".-")[:40]
    return f"{slug or 'subscription'}-{digest}.txt"


def _atomic_write_text(path, text):
    """Write beside the target and ``os.replace``: no partial cache file."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".adblock-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def _bounded_rules(text):
    """Return ``(rules, error)``; an error means the list must not replace cache."""
    rules = []
    seen = set()
    for index, raw in enumerate(str(text or "").splitlines()):
        if index >= MAX_FILTER_LINES:
            return [], "the list has too many lines"
        if len(raw) > MAX_FILTER_LINE_CHARS:
            return [], "a filter line is too long"
        line = raw.strip()
        if not line or line.startswith(("!", "[")):
            continue
        if not _domain_from_filter_line(line):
            # Unsupported syntax (cosmetic filters, regex, options) is skipped
            # by design; it is not silently treated as a domain rule.
            continue
        if line in seen:
            continue
        if len(rules) >= MAX_MERGED_RULES:
            return [], "the list has too many rules"
        seen.add(line)
        rules.append(line)
    return rules, ""


def fetch_and_update_subscriptions(
    base_dir,
    should_cancel=None,
    *,
    timeout: float = safe_http.DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FILTER_FILE_BYTES,
    fetcher=None,
):
    """Download filter lists and replace the merged cache only when it is safe.

    Guarantees:

    * each URL is validated (HTTPS only) before any request;
    * DNS is resolved and every answer validated by ``safe_http``; the socket
      connects to the validated IP, so a redirect cannot reach the local network;
    * a failed, truncated, oversized, malformed or empty download never replaces
      the last known-good cache for that subscription;
    * cache names are derived from a sanitized label + URL hash, so a
      subscription name cannot traverse paths;
    * one subscription failing does not disable the others;
    * status is returned per subscription instead of being swallowed.

    Returns a list of ``{name, status, error, rules}`` dictionaries. Statuses:
    ``updated``, ``unchanged``, ``cached``, ``failed``, ``rejected``,
    ``cancelled``, ``busy``.
    """
    if not _SUBSCRIPTION_LOCK.acquire(blocking=False):
        return [{"name": "", "status": "busy", "error": "Another refresh is already running.", "rules": 0}]
    try:
        from litebrowser.core import prefs

        try:
            configured = prefs.get_adblock_subscriptions(base_dir)
        except Exception:  # noqa: BLE001 - prefs failure must not crash refresh
            configured = []
        if not isinstance(configured, list):
            configured = []

        results = []
        cached_dir = os.path.join(base_dir, "adblock_cache")
        merged = []
        merged_seen = set()
        seen_urls = set()

        for raw in configured[:MAX_SUBSCRIPTIONS]:
            if not isinstance(raw, dict):
                continue
            if should_cancel is not None and should_cancel():
                results.append({"name": "", "status": "cancelled", "error": "Cancelled.", "rules": 0})
                break
            name = str(raw.get("name") or "subscription")[:80]
            raw_url = str(raw.get("url") or "").strip()
            try:
                url = safe_http.normalize_http_url(raw_url)
                scheme = url.split(":", 1)[0].lower()
                if scheme != "https":
                    raise ValueError("Filter lists must be downloaded over HTTPS.")
            except (safe_http.UnsafeUrl, ValueError) as exc:
                results.append(
                    {"name": name, "status": "rejected", "error": str(exc)[:200], "rules": 0}
                )
                _log.warning("subscription %r rejected: %s", name, type(exc).__name__)
                continue
            if url in seen_urls:
                results.append({"name": name, "status": "unchanged", "error": "", "rules": 0})
                continue
            seen_urls.add(url)

            cache_path = os.path.join(cached_dir, _cache_filename(name, url))
            rules = []
            status = "failed"
            error = ""
            try:
                call = fetcher or safe_http.fetch
                request = {
                    "timeout": timeout,
                    "max_bytes": max_bytes,
                    "headers": {
                        "User-Agent": f"Mei/{app_version.APP_VERSION}",
                        "Accept": "text/plain,text/*;q=0.9,*/*;q=0.1",
                    },
                }
                if fetcher is None:
                    # A subscription refresh must follow the same proxy policy
                    # as Page Monitor.  The explicit direct preference is the
                    # only way to bypass a configured app proxy.
                    request["proxy_config"] = prefs.get_proxy_config(base_dir)
                    request["proxy_mode"] = (
                        "direct" if prefs.get_page_monitor_direct(base_dir) else "auto"
                    )
                response = call(url, **request)
                if int(getattr(response, "status", 0) or 0) >= 400:
                    raise ValueError(f"The server returned HTTP {int(response.status)}.")
                text = bytes(getattr(response, "body", b"") or b"").decode("utf-8", errors="replace")
                rules, problem = _bounded_rules(text)
                if problem:
                    raise ValueError(problem)
                if not rules:
                    raise ValueError("The list contained no usable domain rules.")
                previous = ""
                if os.path.isfile(cache_path):
                    with open(cache_path, "r", encoding="utf-8", errors="replace") as handle:
                        previous = handle.read(MAX_FILTER_FILE_BYTES + 1)
                if previous == text:
                    status = "unchanged"
                else:
                    _atomic_write_text(cache_path, text)
                    status = "updated"
            except Exception as exc:  # noqa: BLE001 - per-subscription isolation
                error = str(exc)[:200]
                cached_text = ""
                if os.path.isfile(cache_path):
                    try:
                        with open(cache_path, "r", encoding="utf-8", errors="replace") as handle:
                            cached_text = handle.read(MAX_FILTER_FILE_BYTES + 1)
                    except OSError:
                        cached_text = ""
                rules, problem = _bounded_rules(cached_text) if cached_text else ([], "no cache")
                if rules and not problem:
                    status = "cached"
                    _log.warning("subscription %r failed; using last-known-good cache", name)
                else:
                    status = "failed"
                    _log.warning("subscription %r failed with no usable cache", name)

            for line in rules:
                if line in merged_seen:
                    continue
                if len(merged) >= MAX_MERGED_RULES:
                    break
                merged_seen.add(line)
                merged.append(line)
            results.append({"name": name, "status": status, "error": error, "rules": len(rules)})

        if merged:
            merged_path = os.path.join(cached_dir, "_merged.txt")
            body = chr(10).join(merged)
            previous = ""
            if os.path.isfile(merged_path):
                try:
                    with open(merged_path, "r", encoding="utf-8", errors="replace") as handle:
                        previous = handle.read(MAX_FILTER_FILE_BYTES + 1)
                except OSError:
                    previous = ""
            if previous != body:
                _atomic_write_text(merged_path, body)
            try:
                prefs.set_adblock_filter_file(base_dir, merged_path)
            except Exception:  # noqa: BLE001 - never lose the parsed result over a pref write
                _log.warning("could not point the filter setting at the merged cache")
        return results
    finally:
        _SUBSCRIPTION_LOCK.release()


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
        self.shield_always = False
        self.shield_active = False
        self._shield_custom = set()
        if base_dir:
            self.reload_filter_file()
            self._reload_privacy_prefs()
            self._reload_shield_state()

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
            self.sign_in_compat = bool(prefs.get_chrome_compat_shim(self._base_dir))
            self.shield_always = bool(prefs.get_pref(self._base_dir, "shield_always_on", False))
            self._shield_custom = set(prefs.get_pref(self._base_dir, "shield_custom_hosts", []) or [])
        except Exception:
            pass

    def _reload_shield_state(self):
        """Shield is on when 'always' is set OR a focus pour is running —
        the quiet café kicks distractions out while you work."""
        self.shield_active = bool(
            getattr(self, "shield_always", False) or focus_service.focus_status(self._base_dir).get("running")
        )

    def _is_shielded_host(self, host: str) -> bool:
        if not self.shield_active:
            return False
        if host in self._shield_custom:
            return True
        for domain in _DISTRACTION_HOSTS:
            if host == domain or host.endswith("." + domain):
                return True
        return False

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

    def _apply_compat_headers(self, info, host):
        """Real Client Hints for an allowlisted sign-in origin.

        This is the only compatibility mechanism left. It is network-layer
        (the page's JavaScript is untouched), origin-scoped (see
        ``engine_identity.SIGN_IN_COMPAT_HOSTS``) and opt-in. Values come from
        the running Chromium build, so ``sec-ch-ua`` can never claim a version
        the engine is not, and the brand list names Chromium and Mei rather
        than impersonating Google Chrome.
        """
        from litebrowser.browser import engine_identity

        major, full = _detect_chrome_versions()
        for key, value in engine_identity.client_hint_headers(major, full).items():
            info.setHttpHeader(key, value)
        # A real platform version is Chromium-specific and not exposed to us;
        # omit it rather than assert a Windows build the machine may not run.
        info.setHttpHeader(b"sec-ch-ua-platform-version", b"")

    def _apply_https_upgrade(self, info, url_str):
        """Auto-upgrade http:// to https:// (localhost exempt). Returns True
        when the request was redirected (caller must stop processing)."""
        if not self.https_only or not url_str.startswith("http://"):
            return False
        from urllib.parse import urlparse

        try:
            hostname = (urlparse(url_str).hostname or "").lower()
        except Exception:
            hostname = ""
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
            return False
        # Chrome-style auto-upgrade keeps the page working when the site
        # supports TLS (v6.4 served a bare ERR page instead).
        info.redirect(QUrl("https://" + url_str[len("http://"):]))
        return True

    def interceptRequest(self, info):
        url_str = info.requestUrl().toString()
        host = info.requestUrl().host().lower()
        is_compat = _is_compat_domain(host)
        is_challenge = self._is_trusted_challenge_url(host)
        sign_in_compat = bool(getattr(self, "sign_in_compat", False))
        if is_compat and sign_in_compat:
            # Sign-in origins reject an embedded engine that sends no Client
            # Hints. Send the engine's real ones — never a fabricated Chrome
            # fingerprint, and never on ordinary browsing.
            from litebrowser.browser import engine_identity
            if engine_identity.is_sign_in_host(host):
                self._apply_compat_headers(info, host)
        if not is_challenge:
            info.setHttpHeader(b"DNT", b"1")
            info.setHttpHeader(b"Sec-GPC", b"1")
            # Referrer-Policy is intentionally NOT set as a request header here.
            # Doing so would trigger CORS preflights on cross-origin requests
            # because referrer-policy is not CORS-safelisted and Google et al.
            # don't include it in Access-Control-Allow-Headers.
            # Qt WebEngine already enforces
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

        if self._apply_https_upgrade(info, url_str):
            return

        if is_challenge:
            return
        # Distraction Shield: silent-block social/autoplay while a pour runs
        # (or when 'always on'). Checked after compat hosts so test pages work.
        if self.shield_active and self._is_shielded_host(host):
            info.block(True)
            return
        if self._is_blocked_host(host):
            info.block(True)
            return
