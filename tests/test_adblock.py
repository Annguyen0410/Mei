"""Adblock correctness + hot-path performance (regression test for the O(n*m) loop fix)."""
import time
import unittest

from litebrowser.browser import adblock


class TestAdBlockHostMatching(unittest.TestCase):
    def setUp(self):
        self.blocked = frozenset({
            "doubleclick.net",
            "ads.example.com",
            "tracker.io",
        })

    def _mk(self):
        blk = adblock.TrackingBlocker(base_dir=None)
        blk._all_blocked_domains = self.blocked
        return blk

    def test_exact_match(self):
        blk = self._mk()
        self.assertTrue(blk._is_blocked_host("doubleclick.net"))

    def test_subdomain_match(self):
        blk = self._mk()
        self.assertTrue(blk._is_blocked_host("stats.doubleclick.net"))
        self.assertTrue(blk._is_blocked_host("a.b.ads.example.com"))

    def test_parent_domain_of_blocked_is_not_blocked(self):
        # "example.com" hosts "ads.example.com" but must not be blocked itself.
        blk = self._mk()
        self.assertFalse(blk._is_blocked_host("example.com"))
        self.assertFalse(blk._is_blocked_host("www.example.com"))

    def test_unrelated_host_not_blocked(self):
        blk = self._mk()
        self.assertFalse(blk._is_blocked_host("github.com"))
        self.assertFalse(blk._is_blocked_host("my-tracker.io.evil.org.eo"))  # not suffix of tracker.io

    def test_case_and_trailing_dot_normalised(self):
        blk = self._mk()
        self.assertTrue(blk._is_blocked_host("ADS.EXAMPLE.COM."))

    def test_empty_inputs(self):
        blk = self._mk()
        self.assertFalse(blk._is_blocked_host(""))
        blk._all_blocked_domains = frozenset()
        self.assertFalse(blk._is_blocked_host("doubleclick.net"))


class TestAdBlockPerformance(unittest.TestCase):
    """The old implementation was `for d in blocked: host == d or host.endswith('.'+d)`
    -- O(domains) string scans per request. The suffix-set walk must be dramatically
    faster on a subscription-sized list (5k domains)."""

    def test_hot_path_stays_fast_on_large_list(self):
        domains = adblock._default_blocked_domains() + [
            f"track{i}.example-ads.net" for i in range(5000)
        ]
        blk = adblock.TrackingBlocker(base_dir=None)
        blk._all_blocked_domains = frozenset(domains)

        hosts = ["www.example.com", "ads.track42.example-ads.net", "cdn.github.io"]
        start = time.perf_counter()
        iterations = 6000
        hits = 0
        for _ in range(iterations):
            for h in hosts:
                if blk._is_blocked_host(h):
                    hits += 1
        elapsed = time.perf_counter() - start
        per_lookup_ms = (elapsed / (iterations * len(hosts))) * 1000
        self.assertGreater(hits, 0)
        # New algorithm should be well under 0.05 ms/lookup even on slow CI machines.
        # (Old loop measured ~0.5-1.0 ms/lookup on a 5k list.)
        self.assertLess(
            per_lookup_ms, 0.05,
            f"adblock hot path regressed: {per_lookup_ms:.4f} ms/lookup",
        )


if __name__ == "__main__":
    unittest.main()
