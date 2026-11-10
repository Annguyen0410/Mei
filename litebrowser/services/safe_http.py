"""Outbound HTTP whose destination was actually validated.

The old Page Monitor validated a *hostname string*, then handed the URL to
``urllib``, which resolved the name again and connected wherever DNS pointed the
second time. That is a time-of-check/time-of-use gap: a name that resolved to a
public address during validation can resolve to ``127.0.0.1`` a millisecond
later (DNS rebinding), and a redirect could point anywhere without its
destination being checked at all.

This module closes the gap by making the validated address the address that is
connected to:

* resolve the host once per hop, reject **every** non-public answer (not just
  the first one);
* open the socket to that exact IP with ``socket.create_connection``;
* keep the original hostname for the HTTP ``Host`` header;
* keep the original hostname for TLS SNI and certificate hostname checking, with
  the platform trust store and normal verification — never a bypass;
* validate every redirect as a new destination and re-resolve it;
* bound time, bytes, redirects and header forwarding.

There is deliberately **no proxy support** here. A proxy would mean the TCP
destination is the proxy, so "the validated IP" would no longer be the peer
handling the request. Page Monitor and subscription refresh connect directly; a
network that requires a proxy makes them fail rather than route around the
check. That limitation is documented in the audit instead of being papered over.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import urllib.parse

DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_URL_CHARS = 4096
MAX_REDIRECTS = 5
READ_CHUNK_BYTES = 64 * 1024
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_DEFAULT_HEADERS = {
    "User-Agent": "Mei/1.0 outbound-fetch",
    "Accept": "*/*",
}


class SafeHttpError(RuntimeError):
    """Any failure that prevents a trustworthy response."""


class UnsafeUrl(SafeHttpError, ValueError):
    """The URL itself is not a plain public http(s) target."""


class UnsafeDestination(SafeHttpError):
    """The host resolves to an address this feature must never contact."""


class RedirectError(SafeHttpError):
    """A redirect was unsafe, looping, or too long."""


class FetchTimeout(SafeHttpError):
    """Connecting or reading exceeded the deadline."""


class FetchTLS(SafeHttpError):
    """TLS verification or handshake failed."""


class FetchCancelled(SafeHttpError):
    """The caller asked to stop (application shutdown, user cancel)."""


class FetchProxyUnsupported(SafeHttpError):
    """A proxy is configured, and this transport only connects directly.

    Bypassing a user's proxy policy silently would be a privacy/security bug;
    routing through one would mean the TCP peer is not the validated IP.  The
    only honest outcomes are an explicit error or an explicit direct choice.
    """


#: Checked case-insensitively.  Values are never logged: a proxy URL may carry
#: credentials.
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def proxy_environment() -> tuple[str, ...]:
    """Names (not values) of configured proxy environment variables."""
    return tuple(name for name in PROXY_ENV_VARS if os.environ.get(name, "").strip())


def application_proxy_configured(proxy_config: dict | None) -> bool:
    """Whether Mei's own proxy preference asks for a proxy.

    Only the presence of a configured endpoint matters here; credentials and
    the URL are never included in an error or diagnostic.  A malformed setting
    is treated as configured so it cannot silently fall back to direct.
    """
    if not isinstance(proxy_config, dict):
        return False
    if not bool(proxy_config.get("enabled")):
        return False
    return bool(str(proxy_config.get("host") or "").strip() or str(proxy_config.get("pac_url") or "").strip())


def proxy_policy_status(*, proxy_config: dict | None = None) -> dict:
    """Redacted facts for Diagnostics/Data Management."""
    environment = proxy_environment()
    application = application_proxy_configured(proxy_config)
    return {
        "application_configured": application,
        "environment_variables": list(environment),
        "environment_configured": bool(environment),
        "transport": "direct-only",
        "supports_application_proxy": False,
        "automatic_mode": "refuse" if application or environment else "direct",
    }


class TooLarge(SafeHttpError):
    """The response exceeds the caller's byte budget."""


class CaseInsensitiveHeaders(dict):
    """Small header map whose ``get`` ignores case (server capitalization varies)."""

    def _key(self, name):
        lowered = str(name or "").lower()
        for key in self:
            if str(key).lower() == lowered:
                return key
        return None

    def get(self, name, default=None):
        key = self._key(name)
        return default if key is None else dict.get(self, key)

    def __getitem__(self, name):
        key = self._key(name)
        if key is None:
            raise KeyError(name)
        return dict.__getitem__(self, key)


class SafeResponse:
    """A fully-read response plus a urllib-like surface for existing callers."""

    def __init__(self, url: str, status: int, headers: dict, body: bytes):
        self.url = url
        self.status = int(status)
        self.headers = CaseInsensitiveHeaders(headers or {})
        self._body = bytes(body or b"")
        self._offset = 0

    @property
    def body(self) -> bytes:
        """The complete body (already fully read under the byte budget)."""
        return self._body

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._body):
            return b""
        if size is None or size < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _check_cancel(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise FetchCancelled("The request was cancelled.")


def _literal_ip(host: str):
    try:
        return ipaddress.ip_address(str(host).strip())
    except ValueError:
        return None


def is_public_address(value) -> bool:
    """True only for an address that is globally routable public unicast.

    IPv4-mapped IPv6 is unwrapped first: ``::ffff:127.0.0.1`` is loopback, not a
    public IPv6 address. Documentation ranges, CGNAT, link-local, multicast,
    reserved and unspecified all fail ``is_global`` and are refused explicitly.
    """
    try:
        address = value if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ipaddress.ip_address(str(value))
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    return bool(address.is_global)


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def resolve_public_addresses(host: str, port: int, resolver=None) -> list[str]:
    """Resolve ``host`` once and return only public addresses.

    If *any* answer is non-public the whole host is refused. Accepting it because
    the first answer happened to be public would let round-robin DNS point a
    later connection at the local network.
    """
    literal = _literal_ip(host)
    if literal is not None:
        if not is_public_address(literal):
            raise UnsafeDestination("The host is a local or private address.")
        return [str(literal)]
    resolve = resolver or _default_resolver
    try:
        answers = resolve(host, port)
    except socket.gaierror as exc:
        raise UnsafeDestination("The host name could not be resolved.") from exc
    except OSError as exc:
        raise UnsafeDestination("The host name could not be resolved.") from exc
    addresses: list[str] = []
    if not answers:
        raise UnsafeDestination("The host name resolved to no address.")
    for raw in answers:
        try:
            address = ipaddress.ip_address(str(raw).strip())
        except ValueError as exc:
            raise UnsafeDestination("The host resolved to an invalid address.") from exc
        if not is_public_address(address):
            raise UnsafeDestination("The host resolves to a local or private address.")
        text = str(address)
        if text not in addresses:
            addresses.append(text)
    if not addresses:
        raise UnsafeDestination("The host name resolved to no usable address.")
    return addresses


def normalize_http_url(url: str) -> str:
    """Canonical public http(s) URL, or :class:`UnsafeUrl`.

    Rejects credentials, control characters, non-http schemes, invalid ports and
    malformed IDNs. Fragments are dropped (servers never see them).
    """
    text = str(url or "").strip()
    if not text:
        raise UnsafeUrl("The URL is empty.")
    if len(text) > MAX_URL_CHARS:
        raise UnsafeUrl("The URL is too long.")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text) or any(char.isspace() for char in text):
        raise UnsafeUrl("The URL contains spaces or control characters.")
    try:
        parts = urllib.parse.urlsplit(text)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrl("The URL could not be parsed.") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeUrl("Only http:// and https:// URLs are allowed.")
    if not hostname:
        raise UnsafeUrl("The URL has no host name.")
    if parts.username or parts.password:
        raise UnsafeUrl("Remove the username or password from the URL.")
    if port is not None and not (1 <= port <= 65535):
        raise UnsafeUrl("The URL has an invalid port.")
    host = hostname.strip().rstrip(".").lower()
    literal = _literal_ip(host)
    if literal is not None:
        ascii_host = str(literal)
        netloc = f"[{ascii_host}]" if literal.version == 6 else ascii_host
    else:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise UnsafeUrl("The URL's host name is not valid.") from exc
        netloc = ascii_host
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parts.query, ""))


def redirect_target(current_url: str, location: str, *, allow_downgrade: bool = False) -> str:
    """Resolve one ``Location`` header into a validated next URL.

    HTTPS → HTTP is refused: a monitor or filter list downgrade is a silent
    loss of transport integrity, not a convenience.
    """
    raw = str(location or "").strip()
    if not raw:
        raise RedirectError("The server sent an empty redirect.")
    absolute = urllib.parse.urljoin(current_url, raw)
    target = normalize_http_url(absolute)
    if not allow_downgrade:
        if urllib.parse.urlsplit(current_url).scheme == "https" and urllib.parse.urlsplit(target).scheme == "http":
            raise RedirectError("The page redirected from HTTPS to HTTP; refusing the downgrade.")
    return target


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection whose TCP peer is the already-validated IP."""

    def __init__(self, hostname: str, ip: str, port: int, timeout: float):
        super().__init__(host=hostname, port=port, timeout=timeout)
        self._connect_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._connect_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a pinned IP with SNI and certificate checks on the real hostname."""

    def __init__(self, hostname: str, ip: str, port: int, timeout: float):
        context = ssl.create_default_context()
        super().__init__(host=hostname, port=port, timeout=timeout, context=context)
        self._connect_ip = ip

    def connect(self):
        sock = socket.create_connection((self._connect_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _default_connection(scheme: str, hostname: str, ip: str, port: int, timeout: float):
    if scheme == "https":
        return _PinnedHTTPSConnection(hostname, ip, port, timeout)
    return _PinnedHTTPConnection(hostname, ip, port, timeout)


def _read_limited(response, max_bytes: int, cancelled=None) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        _check_cancel(cancelled)
        chunk = response.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise TooLarge("The response is larger than this feature accepts.")
        chunks.append(chunk)
    return b"".join(chunks)


def _declared_length(response) -> int:
    try:
        raw = response.getheader("Content-Length")
    except Exception:
        return 0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = 2 * 1024 * 1024,
    max_redirects: int = MAX_REDIRECTS,
    headers: dict | None = None,
    resolver=None,
    connection_factory=None,
    cancelled=None,
    proxy_mode: str = "auto",
    proxy_config: dict | None = None,
) -> SafeResponse:
    """Fetch ``url`` with every hop pinned to a validated public address.

    ``resolver`` and ``connection_factory`` exist so tests can exercise the
    policy with no network at all. Production callers pass neither.

    ``proxy_mode`` is ``"auto"`` (default), ``"direct"`` or ``"proxy"``.
    With ``"auto"``, an application-level proxy preference or any HTTP(S)/ALL
    proxy environment variable makes the fetch fail with
    :class:`FetchProxyUnsupported`; it never silently bypasses the policy.
    ``"direct"`` is an explicit application choice.  ``"proxy"`` never falls
    back to direct: this transport has no proxy implementation yet, so it
    reports that honestly.
    """
    if proxy_mode not in ("auto", "direct", "proxy"):
        raise ValueError("proxy_mode must be 'auto', 'direct' or 'proxy'")
    proxy_names = proxy_environment()
    app_proxy = application_proxy_configured(proxy_config)
    if proxy_mode == "proxy":
        raise FetchProxyUnsupported(
            "A supported proxy transport is not implemented in this build; "
            "no direct request was made."
        )
    if (proxy_names or app_proxy) and proxy_mode != "direct":
        source = "Mei's proxy setting" if app_proxy else ", ".join(proxy_names)
        raise FetchProxyUnsupported(
            "A proxy is configured ("
            + source
            + "). This feature cannot use that proxy and will not bypass it silently; "
            "disable the proxy for this feature or choose direct access explicitly."
        )
    try:
        budget = int(max_bytes)
        limit = max(0, int(max_redirects))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_bytes and max_redirects must be integers.") from exc
    if budget <= 0:
        raise ValueError("max_bytes must be positive.")
    current = normalize_http_url(url)
    initial_host = urllib.parse.urlsplit(current).hostname
    sent_headers = dict(_DEFAULT_HEADERS)
    sent_headers.update({str(k): str(v) for k, v in (headers or {}).items()})
    visited = {current}
    hops = 0
    factory = connection_factory or _default_connection
    while True:
        _check_cancel(cancelled)
        parts = urllib.parse.urlsplit(current)
        scheme = parts.scheme
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        addresses = resolve_public_addresses(host, port, resolver)
        ip = addresses[0]
        connection = None
        try:
            connection = factory(scheme, host, ip, port, timeout)
            target = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
            hop_headers = dict(sent_headers)
            if host != initial_host:
                for name in list(hop_headers):
                    if name.lower() in _SENSITIVE_HEADERS:
                        hop_headers.pop(name, None)
            connection.request("GET", target, headers=hop_headers)
            response = connection.getresponse()
            status = int(getattr(response, "status", 0) or 0)
            location = response.getheader("Location") if hasattr(response, "getheader") else None
            if status in REDIRECT_STATUSES and location:
                hops += 1
                if hops > limit:
                    raise RedirectError("The page redirected too many times.")
                nxt = redirect_target(current, location)
                if nxt in visited:
                    raise RedirectError("The page redirect looped.")
                visited.add(nxt)
                current = nxt
                continue
            declared = _declared_length(response)
            if declared > budget:
                raise TooLarge("The response is larger than this feature accepts.")
            body = _read_limited(response, budget, cancelled)
            try:
                response_headers = dict(response.getheaders())
            except Exception:
                response_headers = {}
            return SafeResponse(current, status, response_headers, body)
        except TooLarge:
            raise
        except RedirectError:
            raise
        except FetchCancelled:
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise FetchTimeout("The request timed out.") from exc
        except ssl.SSLError as exc:
            raise FetchTLS("TLS verification failed for this host.") from exc
        except http.client.HTTPException as exc:
            raise SafeHttpError("The server sent an invalid HTTP response.") from exc
        except OSError as exc:
            raise SafeHttpError("Could not connect to the host.") from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def get(url: str, **kwargs) -> SafeResponse:
    """Alias used by callers that read better as ``get``."""
    return fetch(url, **kwargs)


__all__ = [
    "CaseInsensitiveHeaders",
    "DEFAULT_TIMEOUT_SECONDS",
    "FetchCancelled",
    "FetchProxyUnsupported",
    "FetchTLS",
    "FetchTimeout",
    "MAX_REDIRECTS",
    "PROXY_ENV_VARS",
    "RedirectError",
    "SafeHttpError",
    "SafeResponse",
    "TooLarge",
    "UnsafeDestination",
    "UnsafeUrl",
    "fetch",
    "get",
    "is_public_address",
    "normalize_http_url",
    "proxy_environment",
    "redirect_target",
    "resolve_public_addresses",
]
