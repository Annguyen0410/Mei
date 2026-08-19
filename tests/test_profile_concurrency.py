"""Profile RLock + atomic writes: concurrent mutations must not drop records."""
from __future__ import annotations

import concurrent.futures
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import life_service
from litebrowser.services.android_bridge_service import dispatch_ingest


class TestProfileConcurrency(unittest.TestCase):
    def test_concurrent_add_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "profile")
            prefs.ensure_profile_layout(base)
            n = 40

            def add_one(i: int):
                life_service.add_task(base, f"task-{i}", bucket="inbox")

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(add_one, range(n)))

            tasks = life_service.load_tasks(base)
            titles = {t.get("title") for t in tasks}
            self.assertEqual(len(tasks), n, "lost task rows under concurrent add_task")
            self.assertEqual(len(titles), n)

    def test_concurrent_android_create_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "profile")
            prefs.ensure_profile_layout(base)
            n = 30

            def ingest_one(i: int):
                out = dispatch_ingest(
                    base,
                    {"action": "create_task", "payload": {"title": f"mob-{i}", "bucket": "Inbox"}},
                )
                self.assertTrue(out.get("ok"), msg=str(out))

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(ingest_one, range(n)))

            tasks = life_service.load_tasks(base)
            mob_titles = [t.get("title") for t in tasks if str(t.get("title", "")).startswith("mob-")]
            self.assertEqual(len(mob_titles), n)
            self.assertEqual(len(set(mob_titles)), n)


if __name__ == "__main__":
    unittest.main()
