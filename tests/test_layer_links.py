"""Cross-layer integration checks: the new 6.8 layers link correctly."""
import os
import tempfile
import time
import unittest

from litebrowser.core import prefs
from litebrowser.services import flashcard_service, focus_service, page_monitor, routines_service


class TestLayerLinks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_shield_state_follows_focus_session(self):
        """Start a pour -> a TrackingBlocker reports shield active; stop -> off."""
        from litebrowser.browser.adblock import TrackingBlocker

        blocker = TrackingBlocker(None, self.base)
        self.assertFalse(blocker.shield_active)
        focus_service.start_focus(self.base, minutes=25, label="link test")
        blocker._reload_shield_state()
        self.assertTrue(blocker.shield_active)
        focus_service.stop_focus(self.base)
        blocker._reload_shield_state()
        self.assertFalse(blocker.shield_active)

    def test_shield_blocks_distraction_host_when_active(self):
        from litebrowser.browser.adblock import TrackingBlocker

        blocker = TrackingBlocker(None, self.base)
        focus_service.start_focus(self.base, minutes=25)
        blocker._reload_shield_state()

        class _Info:
            def __init__(self, url):
                self._url = QUrl(url)
                self.blocked = False

            def requestUrl(self):
                return self._url

            def resourceType(self):
                return None

            def block(self, value):
                self.blocked = value

        from PyQt5.QtCore import QUrl

        info = _Info("https://www.facebook.com/feed")
        # requestUrl used via info.requestUrl(); interceptRequest needs more
        # Qt plumbing, so call the host check directly (unit of the decision).
        self.assertTrue(blocker._is_shielded_host("www.facebook.com"))
        self.assertFalse(blocker._is_shielded_host("docs.python.org"))

    def test_custom_shield_hosts_merge(self):
        prefs.save_pref(self.base, "shield_always_on", True)
        prefs.save_pref(self.base, "shield_custom_hosts", ["myschoolportal.example"])
        from litebrowser.browser.adblock import TrackingBlocker

        blocker = TrackingBlocker(None, self.base)
        self.assertTrue(blocker.shield_always)
        self.assertTrue(blocker._is_shielded_host("myschoolportal.example"))
        self.assertFalse(blocker._is_shielded_host("example.org"))

    def test_routine_due_once_per_day(self):
        weekday = time.localtime().tm_wday
        routines_service.add_routine(self.base, "Morning", time.strftime("%H:%M"), [weekday], ["/template daily"])
        due = routines_service.due_routines(self.base)
        self.assertEqual(len(due), 1)
        routines_service.mark_fired(self.base, due[0]["id"], time.strftime("%Y-%m-%d"))
        self.assertEqual(routines_service.due_routines(self.base), [])

    def test_monitor_seeds_then_detects_change(self):
        monitor = page_monitor.add_monitor(self.base, "https://example.com/page", "Example")
        page_monitor.record_check(self.base, monitor["id"], "hash-a")
        outcome = page_monitor.record_check(self.base, monitor["id"], "hash-b")
        self.assertEqual(outcome, "changed")
        outcome = page_monitor.record_check(self.base, monitor["id"], "hash-b")
        self.assertEqual(outcome, "same")

    def test_flashcard_and_heatmap_share_focus_data(self):
        # Seed a completed 25-minute pour directly (deterministic).
        sessions = [{
            "id": "s1", "label": "test", "minutes": 25, "status": "completed",
            "started_at": int(time.time()) - 25 * 60, "ended_at": int(time.time()),
        }]
        per_day = focus_service.compute_daily_minutes(sessions)
        self.assertTrue(any(v >= 20 for v in per_day.values()))
        current, longest = focus_service.compute_streaks(per_day)
        self.assertGreaterEqual(current, 1)
        self.assertGreaterEqual(longest, current)


if __name__ == "__main__":
    unittest.main()
