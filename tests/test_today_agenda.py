"""Home agenda: planner deadlines and the legacy quick-task inbox in one view.

The two task systems stay separate in storage — this view is what makes Home
answer "what is on my plate today?" without a data migration.
"""
import os
import tempfile
import time
import unittest
from datetime import date, timedelta

from litebrowser.core import prefs
from litebrowser.services import life_service, personal_plan


class TestTodayAgenda(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.today = date.today().isoformat()
        self.yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.tomorrow = (date.today() + timedelta(days=1)).isoformat()

    def tearDown(self):
        self._tmp.cleanup()

    def test_both_systems_appear_with_their_source(self):
        life_service.add_task(self.base, "Inbox task", bucket="today")
        personal_plan.create_item(self.base, "Essay", scheduled_date=self.today)
        personal_plan.create_time_block(self.base, "Deep work", self.today, 540)

        agenda = life_service.today_agenda(self.base)
        sources = {(entry["source"], entry["kind"]) for entry in agenda["items"]}
        self.assertIn(("inbox", "task"), sources)
        self.assertIn(("planner", "planner-item"), sources)
        self.assertIn(("planner", "planner-block"), sources)
        self.assertEqual(agenda["counts"]["inbox"], 1)
        self.assertEqual(agenda["counts"]["planner"], 2)
        self.assertEqual(agenda["date"], self.today)

    def test_overdue_items_come_first_and_completed_disappear(self):
        overdue = personal_plan.create_item(self.base, "Late essay", due_date=self.yesterday)
        personal_plan.create_item(self.base, "Today essay", due_date=self.today)

        agenda = life_service.today_agenda(self.base)
        self.assertEqual([entry["title"] for entry in agenda["items"]], ["Late essay", "Today essay"])
        self.assertTrue(agenda["items"][0]["overdue"])
        self.assertEqual(agenda["counts"]["overdue"], 1)

        personal_plan.complete_item(self.base, overdue["id"])
        titles = [entry["title"] for entry in life_service.today_agenda(self.base)["items"]]
        self.assertNotIn("Late essay", titles)

    def test_other_days_are_ignored(self):
        personal_plan.create_item(self.base, "Tomorrow essay", scheduled_date=self.tomorrow)
        life_service.add_task(self.base, "Later task", due_at=int(time.time()) + 86400)

        titles = [entry["title"] for entry in life_service.today_agenda(self.base)["items"]]
        self.assertEqual(titles, [])

    def test_overdue_inbox_task_surfaces(self):
        life_service.add_task(self.base, "Overdue inbox", due_at=int(time.time()) - 86400)
        agenda = life_service.today_agenda(self.base)
        self.assertEqual([entry["source"] for entry in agenda["items"]], ["inbox"])
        self.assertTrue(agenda["items"][0]["overdue"])

    def test_blocks_sort_before_untimed_items(self):
        personal_plan.create_item(self.base, "Timeless item", due_date=self.today)
        personal_plan.create_time_block(self.base, "Morning block", self.today, 480)
        titles = [entry["title"] for entry in life_service.today_agenda(self.base)["items"]]
        self.assertEqual(titles, ["Morning block", "Timeless item"])


if __name__ == "__main__":
    unittest.main()
