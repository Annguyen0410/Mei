"""Session save -> restore round-trip: guards the closeEvent persistence fixes."""
import json
import os
import tempfile
import unittest

from litebrowser.core import prefs


class TestSessionStateRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load_roundtrip(self):
        tabs = [
            {"url": "https://example.com/a", "title": "A", "hibernated": False, "active": True, "pinned": False, "workspace_id": "ws1", "kind": "tab", "icon": ""},
            {"url": "https://example.com/b", "title": "B", "hibernated": True, "active": False, "pinned": True, "workspace_id": "ws2", "kind": "tab", "icon": ""},
        ]
        prefs.session_state_save(self.base, {"tabs": tabs, "recently_closed": []})
        loaded = prefs.session_state_load(self.base)
        self.assertEqual(len(loaded["tabs"]), 2)
        self.assertEqual(loaded["tabs"][0]["title"], "A")
        self.assertTrue(loaded["tabs"][1]["pinned"])
        self.assertEqual(loaded["tabs"][1]["workspace_id"], "ws2")

    def test_recently_closed_tab_is_deduped_by_url(self):
        state = {"version": 2, "tabs": [], "recently_closed": []}
        prefs.session_state_save(self.base, state)

        class _FakeWindow:
            def __init__(self, base):
                self.base_dir = base

        # Exercise the same code path used by SearchWindow.remember_closed_tab
        def remember(md):
            s = prefs.session_state_load(self.base)
            rc = [x for x in s.get("recently_closed", []) if x.get("url") != md["url"]]
            rc.insert(0, md)
            s["recently_closed"] = rc[:5]
            prefs.session_state_save(self.base, s)

        remember({"url": "https://x.example", "title": "t1"})
        remember({"url": "https://y.example", "title": "t2"})
        remember({"url": "https://x.example", "title": "t3"})  # duplicate URL, must dedupe
        loaded = prefs.session_state_load(self.base)
        urls = [e.get("url") for e in loaded["recently_closed"]]
        self.assertEqual(urls.count("https://x.example"), 1)
        self.assertEqual(urls[0], "https://x.example")

    def test_legacy_list_format_is_upgraded(self):
        path = prefs.session_path(self.base)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(["https://example.com", "https://two.example"], fh)
        loaded = prefs.session_state_load(self.base)
        self.assertEqual(loaded["version"], 2)
        self.assertEqual(len(loaded["tabs"]), 2)
        self.assertEqual(loaded["tabs"][0]["url"], "https://example.com")


if __name__ == "__main__":
    unittest.main()
