"""The outbound transport must connect only to an address it validated.

Every test here is offline: DNS is a function, the connection is a fake that
records which IP it was told to dial, and responses are byte strings. That is
the point — the guarantee is about the address handed to the socket, which can
be asserted without touching a network.
"""
import socket
import ssl
import unittest
from unittest import mock

from litebrowser.services import safe_http


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None):
        self._body = body
        self.status = status
        self._headers = dict(headers or {})
        self._read = False

    def read(self, size=-1):
        if self._read:
            return b""
        self._read = True
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def getheader(self, name, default=None):
        for key, value in self._headers.items():
            if key.lower() == str(name).lower():
                return value
        return default

    def getheaders(self):
        return list(self._headers.items())


class FakeConnection:
    def __init__(self, response, record):
        self._response = response
        self._record = record
        self.closed = False

    def request(self, method, target, headers=None):
        self._record.append({"method": method, "target": target, "headers": dict(headers or {})})

    def getresponse(self):
        return self._response

    def close(self):
        self.closed = True


def _factory(response, record, error=None):
    def build(scheme, host, ip, port, timeout):
        record.append({"scheme": scheme, "host": host, "ip": ip, "port": port, "timeout": timeout})
        if error is not None:
            raise error
        return FakeConnection(response, record)

    return build


class TestAddressPolicy(unittest.TestCase):
    def test_public_addresses_are_accepted(self):
        self.assertTrue(safe_http.is_public_address("93.184.216.34"))
        self.assertTrue(safe_http.is_public_address("2606:4700:4700::1111"))

    def test_non_public_addresses_are_refused(self):
        for value in (
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "fe80::1",
            "fc00::1",
            "ff02::1",
            "::",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.5",
            "100.64.0.1",
            "192.0.2.10",
        ):
            with self.subTest(value=value):
                self.assertFalse(safe_http.is_public_address(value))

    def test_any_private_answer_refuses_the_whole_host(self):
        resolver = lambda host, port: ["93.184.216.34", "10.0.0.5"]
        with self.assertRaises(safe_http.UnsafeDestination):
            safe_http.resolve_public_addresses("example.com", 443, resolver)

    def test_public_ipv6_literal_is_allowed(self):
        self.assertEqual(
            safe_http.resolve_public_addresses("2606:4700:4700::1111", 443),
            ["2606:4700:4700::1111"],
        )

    def test_private_literal_is_refused_before_dns(self):
        self.assertRaises(
            safe_http.UnsafeDestination,
            safe_http.resolve_public_addresses,
            "127.0.0.1",
            80,
        )


class TestUrlPolicy(unittest.TestCase):
    def test_public_ipv6_literal_is_canonicalised_with_brackets(self):
        self.assertEqual(
            safe_http.normalize_http_url("https://[2606:4700:4700::1111]/a"),
            "https://[2606:4700:4700::1111]/a",
        )

    def test_unsafe_urls_are_refused(self):
        for value in (
            "javascript:alert(1)",
            "file:///C:/Windows/win.ini",
            "ftp://example.com/x",
            "https://user:pass@example.com/",
            "https://example.com/a b",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises(safe_http.UnsafeUrl):
                    safe_http.normalize_http_url(value)


class TestPinnedFetch(unittest.TestCase):
    def test_connects_to_the_validated_ip_not_the_hostname(self):
        record = []
        response = FakeResponse(b"hello")
        resolver_calls = []

        def resolver(host, port):
            resolver_calls.append((host, port))
            return ["93.184.216.34"]

        result = safe_http.fetch(
            "https://example.com/page",
            resolver=resolver,
            connection_factory=_factory(response, record),
        )
        self.assertEqual(result.body, b"hello")
        self.assertEqual(resolver_calls, [("example.com", 443)], "resolved exactly once")
        connection = record[0]
        self.assertEqual(connection["host"], "example.com", "Host/SNI keeps the real name")
        self.assertEqual(connection["ip"], "93.184.216.34")
        self.assertEqual(record[1]["headers"].get("User-Agent", "").startswith("Mei/"), True)

    def test_http_uses_port_80_and_https_443(self):
        for url, port in (("http://example.com/", 80), ("https://example.com/", 443)):
            record = []
            safe_http.fetch(
                url,
                resolver=lambda host, p: ["93.184.216.34"],
                connection_factory=_factory(FakeResponse(b"x"), record),
            )
            with self.subTest(url=url):
                self.assertEqual(record[0]["port"], port)

    def test_declared_oversized_response_is_refused_before_reading(self):
        with self.assertRaises(safe_http.TooLarge):
            safe_http.fetch(
                "https://example.com/",
                max_bytes=16,
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(
                    FakeResponse(b"tiny", headers={"Content-Length": "9999"}), []
                ),
            )

    def test_streamed_oversized_response_is_refused(self):
        with self.assertRaises(safe_http.TooLarge):
            safe_http.fetch(
                "https://example.com/",
                max_bytes=4,
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(FakeResponse(b"0123456789"), []),
            )

    def test_empty_response_is_valid(self):
        result = safe_http.fetch(
            "https://example.com/",
            resolver=lambda host, port: ["93.184.216.34"],
            connection_factory=_factory(FakeResponse(b""), []),
        )
        self.assertEqual(result.body, b"")
        self.assertEqual(result.status, 200)

    def test_http_error_status_is_returned_to_the_caller(self):
        result = safe_http.fetch(
            "https://example.com/",
            resolver=lambda host, port: ["93.184.216.34"],
            connection_factory=_factory(FakeResponse(b"nope", status=503), []),
        )
        self.assertEqual(result.status, 503)

    def test_timeout_is_reported_as_a_timeout(self):
        class Slow(FakeResponse):
            def read(self, size=-1):
                raise socket.timeout("timed out")

        with self.assertRaises(safe_http.FetchTimeout):
            safe_http.fetch(
                "https://example.com/",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(Slow(b"x"), []),
            )

    def test_tls_verification_failure_is_reported(self):
        with self.assertRaises(safe_http.FetchTLS):
            safe_http.fetch(
                "https://example.com/",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(
                    FakeResponse(b""), [], error=ssl.SSLCertVerificationError("bad cert")
                ),
            )

    def test_proxy_environment_refuses_silent_direct_access(self):
        """A proxy env var must not become an unvalidated hop *or* be ignored.

        Behaviour changed deliberately: the old transport ignored proxy settings
        entirely, which silently bypassed the user's proxy policy.  With the
        default ``auto`` mode a configured proxy is now a typed refusal; direct
        access is available only when the caller asks for it explicitly.
        """
        record = []
        with mock.patch.dict(
            "os.environ",
            {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"},
        ):
            with self.assertRaises(safe_http.FetchProxyUnsupported):
                safe_http.fetch(
                    "https://example.com/",
                    resolver=lambda host, port: ["93.184.216.34"],
                    connection_factory=_factory(FakeResponse(b"ok"), record),
                )
            response = safe_http.fetch(
                "https://example.com/",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(FakeResponse(b"ok"), record),
                proxy_mode="direct",
            )
        self.assertEqual(record[0]["ip"], "93.184.216.34")
        self.assertEqual(response.body, b"ok")

    def test_application_proxy_refuses_and_direct_is_explicit(self):
        record = []
        config = {"enabled": True, "host": "proxy.local", "port": 8080, "password": "secret"}
        with self.assertRaises(safe_http.FetchProxyUnsupported):
            safe_http.fetch(
                "https://example.com/",
                proxy_config=config,
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(FakeResponse(b"ok"), record),
            )
        response = safe_http.fetch(
            "https://example.com/",
            proxy_config=config,
            proxy_mode="direct",
            resolver=lambda host, port: ["93.184.216.34"],
            connection_factory=_factory(FakeResponse(b"ok"), record),
        )
        self.assertEqual(response.body, b"ok")
        policy = safe_http.proxy_policy_status(proxy_config=config)
        self.assertTrue(policy["application_configured"])
        self.assertNotIn("secret", repr(policy))

    def test_proxy_mode_never_falls_back_to_direct(self):
        with self.assertRaises(safe_http.FetchProxyUnsupported):
            safe_http.fetch("https://example.com/", proxy_mode="proxy")

    def test_cancellation_stops_before_connecting(self):
        with self.assertRaises(safe_http.FetchCancelled):
            safe_http.fetch(
                "https://example.com/",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(FakeResponse(b""), []),
                cancelled=lambda: True,
            )


class TestRedirects(unittest.TestCase):
    def _redirect(self, location):
        return FakeResponse(b"", status=302, headers={"Location": location})

    def test_redirect_to_localhost_is_refused(self):
        record = []
        with self.assertRaises(safe_http.UnsafeDestination):
            safe_http.fetch(
                "https://example.com/start",
                resolver=lambda host, port: ["93.184.216.34"] if host == "example.com" else [],
                connection_factory=_factory(self._redirect("https://127.0.0.1/admin"), record),
            )
        self.assertEqual(record[0]["ip"], "93.184.216.34")

    def test_redirect_to_a_host_that_now_resolves_private_is_refused(self):
        calls = []

        def resolver(host, port):
            calls.append(host)
            # The first (attacker-controlled) host is public; the redirect target
            # resolves to the local network. This is the rebinding shape.
            return ["93.184.216.34"] if host == "public.example" else ["10.0.0.7"]

        record = []

        def factory(scheme, host, ip, port, timeout):
            record.append((host, ip))
            if len(record) == 1:
                return FakeConnection(self._redirect("https://internal.example/admin"), [])
            return FakeConnection(FakeResponse(b"secret"), [])

        with self.assertRaises(safe_http.UnsafeDestination):
            safe_http.fetch("https://public.example/", resolver=resolver, connection_factory=factory)
        self.assertEqual(record, [("public.example", "93.184.216.34")])
        self.assertEqual(calls, ["public.example", "internal.example"])

    def test_https_to_http_downgrade_is_refused(self):
        with self.assertRaises(safe_http.RedirectError):
            safe_http.fetch(
                "https://example.com/",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(self._redirect("http://example.com/"), []),
            )

    def test_redirect_loop_is_refused(self):
        record = []
        with self.assertRaises(safe_http.RedirectError):
            safe_http.fetch(
                "https://example.com/a",
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=_factory(self._redirect("https://example.com/a"), record),
            )

    def test_redirect_limit_is_finite(self):
        record = []

        def factory(scheme, host, ip, port, timeout):
            record.append(ip)
            return FakeConnection(self._redirect(f"https://example.com/{len(record)}"), [])

        with self.assertRaises(safe_http.RedirectError):
            safe_http.fetch(
                "https://example.com/0",
                max_redirects=2,
                resolver=lambda host, port: ["93.184.216.34"],
                connection_factory=factory,
            )
        self.assertLessEqual(len(record), 3)

    def test_sensitive_headers_are_not_forwarded_across_origins(self):
        seen = []

        def factory(scheme, host, ip, port, timeout):
            class Conn:
                def request(self, method, target, headers=None):
                    seen.append((host, dict(headers or {})))

                def getresponse(self):
                    if len(seen) == 1:
                        return FakeResponse(
                            b"", status=302, headers={"Location": "https://other.example/next"}
                        )
                    return FakeResponse(b"ok")

                def close(self):
                    return None

            return Conn()

        safe_http.fetch(
            "https://example.com/",
            headers={"Authorization": "Bearer secret", "Cookie": "sid=1"},
            resolver=lambda host, port: ["93.184.216.34"],
            connection_factory=factory,
        )
        self.assertEqual([host for host, _ in seen], ["example.com", "other.example"])
        self.assertIn("Authorization", seen[0][1])
        self.assertNotIn("Authorization", seen[1][1])
        self.assertNotIn("Cookie", seen[1][1])

    def test_redirect_target_normalises_the_location(self):
        self.assertEqual(
            safe_http.redirect_target("https://example.com/a", "../b"),
            "https://example.com/b",
        )


if __name__ == "__main__":
    unittest.main()
