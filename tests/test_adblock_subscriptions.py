"""Subscription refresh: hostile lists, failed updates, and cache survival.

No network is used. A fake fetcher returns bytes, and every assertion is about
what reached the cache: a bad list must never replace the last known-good one,
and a subscription name must never become a path.
"""
import os
import tempfile
import unittest

from litebrowser.browser import adblock
from litebrowser.core import prefs
from litebrowser.services import safe_http


class _Resp:
    def __init__(self, body=b"", status=200):
        self.body = body
        self.status = status


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.cache = os.path.join(self.base, "adblock_cache")

    def tearDown(self):
        self._tmp.cleanup()

    def _subs(self, *pairs):
        prefs.set_adblock_subscriptions(
            self.base, [{"name": name, "url": url} for name, url in pairs]
        )

    def _cache_files(self):
        if not os.path.isdir(self.cache):
            return []
        return sorted(os.listdir(self.cache))


class TestValidation(_Base):
    def test_plain_http_is_rejected_without_a_request(self):
        self._subs(("Insecure", "http://example.com/list.txt"))
        calls = []
        result = adblock.fetch_and_update_subscriptions(
            self.base, fetcher=lambda *a, **k: calls.append(a) or _Resp()
        )
        self.assertEqual(result[0]["status"], "rejected")
        self.assertEqual(calls, [])

    def test_unsupported_schemes_are_rejected(self):
        for url in ("file:///C:/filters.txt", "ftp://example.com/x", "javascript:alert(1)"):
            with self.subTest(url=url):
                self._subs(("Bad", url))
                result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp())
                self.assertEqual(result[0]["status"], "rejected")

    def test_duplicate_urls_are_fetched_once(self):
        self._subs(("One", "https://example.com/list.txt"), ("Two", "https://example.com/list.txt"))
        calls = []

        def fetcher(*args, **kwargs):
            calls.append(args[0])
            return _Resp(b"||ads.example.com^")

        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=fetcher)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result[1]["status"], "unchanged")

    def test_subscription_name_cannot_traverse_paths(self):
        self._subs(("../../escape", "https://example.com/list.txt"))
        adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(b"||ads.example.com^"))
        for name in self._cache_files():
            self.assertNotIn("..", name)
            self.assertNotIn(os.sep, name)
        self.assertFalse(os.path.exists(os.path.join(self.base, "escape")))


class TestCacheSafety(_Base):
    GOOD = b"||ads.example.com^\n||tracker.example^\n"

    def test_a_good_list_is_cached_atomically(self):
        self._subs(("Good", "https://example.com/list.txt"))
        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(self.GOOD))
        self.assertEqual(result[0]["status"], "updated")
        self.assertTrue(os.path.isfile(os.path.join(self.cache, "_merged.txt")))
        self.assertFalse(any(name.endswith(".tmp") for name in self._cache_files()))
        self.assertEqual(
            prefs.get_adblock_filter_file(self.base),
            os.path.join(self.cache, "_merged.txt"),
        )

    def test_an_identical_refresh_is_unchanged_and_keeps_one_file(self):
        self._subs(("Good", "https://example.com/list.txt"))
        adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(self.GOOD))
        before = set(self._cache_files())
        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(self.GOOD))
        self.assertEqual(result[0]["status"], "unchanged")
        self.assertEqual(set(self._cache_files()), before)

    def test_a_failed_update_keeps_the_last_known_good_cache(self):
        self._subs(("Good", "https://example.com/list.txt"))
        adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(self.GOOD))
        cache_files = [name for name in self._cache_files() if name != "_merged.txt"]
        self.assertEqual(len(cache_files), 1)
        cached_path = os.path.join(self.cache, cache_files[0])
        with open(cached_path, "rb") as handle:
            original = handle.read()

        def fails(*args, **kwargs):
            raise safe_http.FetchTimeout("timed out")

        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=fails)
        self.assertEqual(result[0]["status"], "cached")
        self.assertIn("timed out", result[0]["error"])
        with open(cached_path, "rb") as handle:
            self.assertEqual(handle.read(), original)

    def test_an_empty_list_never_replaces_the_cache(self):
        self._subs(("Good", "https://example.com/list.txt"))
        adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(self.GOOD))
        cache_files = [name for name in self._cache_files() if name != "_merged.txt"]
        cached_path = os.path.join(self.cache, cache_files[0])
        with open(cached_path, "rb") as handle:
            original = handle.read()

        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(b""))
        self.assertEqual(result[0]["status"], "cached")
        with open(cached_path, "rb") as handle:
            self.assertEqual(handle.read(), original)

    def test_a_malformed_list_never_replaces_the_cache(self):
        self._subs(("Good", "https://example.com/list.txt"))
        result = adblock.fetch_and_update_subscriptions(
            self.base, fetcher=lambda *a, **k: _Resp(b"<html>not a filter list</html>")
        )
        self.assertEqual(result[0]["status"], "failed")
        self.assertEqual(result[0]["rules"], 0)
        self.assertFalse(os.path.isfile(os.path.join(self.cache, "_merged.txt")))

    def test_http_error_status_is_a_failure(self):
        self._subs(("Good", "https://example.com/list.txt"))
        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(b"x", status=503))
        self.assertEqual(result[0]["status"], "failed")
        self.assertIn("503", result[0]["error"])

    def test_one_failure_does_not_disable_another_subscription(self):
        self._subs(
            ("Bad", "https://bad.example/list.txt"),
            ("Good", "https://good.example/list.txt"),
        )

        def fetcher(url, **kwargs):
            if "bad." in url:
                raise safe_http.SafeHttpError("offline")
            return _Resp(b"||ads.example.com^")

        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=fetcher)
        self.assertEqual(result[0]["status"], "failed")
        self.assertEqual(result[1]["status"], "updated")
        self.assertTrue(os.path.isfile(os.path.join(self.cache, "_merged.txt")))


class TestBounds(_Base):
    def test_an_overlong_filter_line_rejects_the_list(self):
        self._subs(("Good", "https://example.com/list.txt"))
        body = ("a" * (adblock.MAX_FILTER_LINE_CHARS + 1)).encode()
        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=lambda *a, **k: _Resp(body))
        self.assertEqual(result[0]["status"], "failed")
        self.assertIn("too long", result[0]["error"])

    def test_too_many_lines_rejects_the_list(self):
        self._subs(("Good", "https://example.com/list.txt"))
        with unittest.mock.patch.object(adblock, "MAX_FILTER_LINES", 5):
            body = b"\n".join(b"||a%d.example^" % i for i in range(10))
            result = adblock.fetch_and_update_subscriptions(
                self.base, fetcher=lambda *a, **k: _Resp(body)
            )
        self.assertEqual(result[0]["status"], "failed")
        self.assertIn("too many lines", result[0]["error"])

    def test_oversized_response_is_not_written(self):
        self._subs(("Good", "https://example.com/list.txt"))

        def too_big(*args, **kwargs):
            raise safe_http.TooLarge("too large")

        result = adblock.fetch_and_update_subscriptions(self.base, fetcher=too_big)
        self.assertEqual(result[0]["status"], "failed")

    def test_the_parser_skips_unsupported_syntax_instead_of_guessing(self):
        rules, error = adblock._bounded_rules(
            b"! comment\n[Adblock Plus 2.0]\n##.cosmetic\n/ads[0-9]+/\n||good.example^\n".decode()
        )
        self.assertEqual(error, "")
        self.assertEqual(rules, ["||good.example^"])

    def test_filter_file_reading_is_bounded(self):
        path = os.path.join(self._tmp.name, "filters.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("||good.example^\n")
            handle.write("a" * (adblock.MAX_FILTER_LINE_CHARS + 1) + "\n")
        self.assertEqual(adblock.load_domains_from_filter_file(path), {"good.example"})


class TestConcurrencyAndCancel(_Base):
    def test_a_second_refresh_reports_busy_instead_of_racing(self):
        self._subs(("Good", "https://example.com/list.txt"))
        self.assertTrue(adblock._SUBSCRIPTION_LOCK.acquire(blocking=False))
        try:
            result = adblock.fetch_and_update_subscriptions(
                self.base, fetcher=lambda *a, **k: _Resp(b"||ads.example.com^")
            )
        finally:
            adblock._SUBSCRIPTION_LOCK.release()
        self.assertEqual(result[0]["status"], "busy")

    def test_cancellation_stops_before_fetching(self):
        self._subs(("Good", "https://example.com/list.txt"))
        calls = []
        result = adblock.fetch_and_update_subscriptions(
            self.base,
            should_cancel=lambda: True,
            fetcher=lambda *a, **k: calls.append(1) or _Resp(b"||ads.example.com^"),
        )
        self.assertEqual(result[0]["status"], "cancelled")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
