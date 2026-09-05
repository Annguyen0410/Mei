"""Regression checks for malformed self-hosted sync snapshots."""
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import life_service, sync_service


class TestSyncServiceSafety(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_malformed_rows_are_ignored_without_crashing_pull(self):
        local = life_service.add_task(self.base, "Keep me")
        applied = sync_service._apply_bundle(
            self.base,
            {
                "tasks": ["invalid", {"id": "remote", "title": "Remote task"}],
                "events": [None],
                "boards": {"not": "a list"},
                "saved_pages": [42],
                "notes": ["invalid"],
                "bookmarks": ["invalid"],
                "history": ["invalid", ["not-a-time", "https://bad.example"], [123, "https://ok.example"]],
            },
        )

        self.assertEqual(applied["tasks"], 1)
        self.assertEqual(applied["events"], 0)
        self.assertEqual(applied["history"], 1)
        self.assertEqual({task["id"] for task in life_service.load_tasks(self.base)}, {local["id"], "remote"})

    def test_upsert_does_not_mutate_remote_rows(self):
        incoming = [{"id": "remote", "title": "Remote task"}]
        merged = sync_service._upsert([], incoming)
        merged[0]["title"] = "Changed locally"
        self.assertEqual(incoming[0]["title"], "Remote task")


if __name__ == "__main__":
    unittest.main()
