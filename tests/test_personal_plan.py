"""Weekly student planner data contract and persistence tests."""
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import personal_plan


class TestPersonalPlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_plan_has_stable_schema(self):
        plan = personal_plan.load_plan(self.base)
        self.assertEqual(plan["version"], personal_plan.PLAN_VERSION)
        self.assertEqual(plan["academic_week_start"], "monday")
        self.assertEqual(plan["items"], [])
        self.assertEqual(plan["courses"], [])
        self.assertEqual(plan["time_blocks"], [])

    def test_item_roundtrip_normalizes_weekly_fields(self):
        course = personal_plan.create_course(
            self.base,
            "Algorithms",
            code="CS301",
            schedule="Tue 09:00",
        )
        item = personal_plan.create_item(
            self.base,
            "Finish graph assignment",
            kind="assignment",
            course_id=course["id"],
            scheduled_date="2026-09-08",
            due_date="2026-09-10",
            priority="HIGH",
            category="Homework",
            tags=["graphs", "Graphs", "week 2"],
            recurrence="weekly",
            duration_minutes=90,
        )
        self.assertEqual(item["kind"], "assignment")
        self.assertEqual(item["priority"], "high")
        self.assertEqual(item["tags"], ["graphs", "week 2"])
        self.assertEqual(item["duration_minutes"], 90)

        loaded = personal_plan.load_plan(self.base)
        self.assertEqual(loaded["items"][0]["title"], "Finish graph assignment")
        self.assertEqual(loaded["items"][0]["course_id"], course["id"])
        self.assertTrue(os.path.isfile(personal_plan.plan_path(self.base)))

    def test_week_query_includes_scheduled_or_due_items_and_blocks(self):
        personal_plan.create_item(self.base, "Monday task", scheduled_date="2026-09-07")
        personal_plan.create_item(self.base, "Friday deadline", due_date="2026-09-11")
        personal_plan.create_item(self.base, "Next week", due_date="2026-09-14")
        block = personal_plan.create_time_block(
            self.base,
            "Deep study",
            "2026-09-09",
            9 * 60,
            duration_minutes=120,
        )

        week = personal_plan.items_for_week(self.base, "2026-09-09")
        self.assertEqual(week["week_start"], "2026-09-07")
        self.assertEqual(week["week_end"], "2026-09-13")
        self.assertEqual(
            {item["title"] for item in week["items"]},
            {"Monday task", "Friday deadline"},
        )
        self.assertEqual(week["time_blocks"][0]["id"], block["id"])

    def test_completion_update_and_delete_cascade_time_blocks(self):
        item = personal_plan.create_item(self.base, "Read chapter", scheduled_date="2026-09-08")
        block = personal_plan.create_time_block(
            self.base,
            "Reading block",
            "2026-09-08",
            10 * 60,
            item_id=item["id"],
        )
        updated = personal_plan.complete_item(self.base, item["id"])
        self.assertTrue(updated["completed"])
        self.assertTrue(personal_plan.delete_item(self.base, item["id"]))
        self.assertFalse(personal_plan.delete_time_block(self.base, block["id"]))
        self.assertEqual(personal_plan.load_plan(self.base)["items"], [])
        self.assertEqual(personal_plan.load_plan(self.base)["time_blocks"], [])

    def test_invalid_input_is_rejected_without_corrupting_plan(self):
        with self.assertRaises(ValueError):
            personal_plan.create_item(self.base, "")
        with self.assertRaises(ValueError):
            personal_plan.create_time_block(self.base, "Block", "not-a-date", 60)
        self.assertEqual(personal_plan.load_plan(self.base)["items"], [])

    def test_malformed_collections_are_recovered_as_empty(self):
        with open(personal_plan.plan_path(self.base), "w", encoding="utf-8") as handle:
            handle.write('{"items": {"bad": true}, "courses": "bad", "time_blocks": null}')
        plan = personal_plan.load_plan(self.base)
        self.assertEqual(plan["items"], [])
        self.assertEqual(plan["courses"], [])
        self.assertEqual(plan["time_blocks"], [])

    def test_weekly_plan_is_registered_in_personal_palette(self):
        from litebrowser.ui.dialogs.shell_palette import _PERSONAL_PAGES

        keys = {key for key, _label, _glyph in _PERSONAL_PAGES}
        self.assertIn("plan", keys)

    def test_weekly_plan_uses_qdate_days_to_and_drop_mode(self):
        import inspect

        from litebrowser.ui.personal_window import PersonalWindow, PlannerDayList

        page_source = inspect.getsource(PersonalWindow._refresh_plan)
        build_source = inspect.getsource(PersonalWindow._build_plan_page)
        day_source = inspect.getsource(PlannerDayList)
        self.assertGreaterEqual(page_source.count("start.daysTo("), 2)
        self.assertIn("self.DragDropMode.DragDrop", day_source)
        self.assertIn("_planner_sync_due_date", build_source)
        self.assertIn("Guide: choose a date", build_source)


if __name__ == "__main__":
    unittest.main()
