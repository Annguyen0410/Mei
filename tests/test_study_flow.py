"""The study loop: one recommendation read from every store at once.

Covers the priority ladder (running pour → overdue → today → blocks → cards →
inbox → fresh captures → plan the week), the per-step counters, the inbox→planner
hand-off (`promote_task`) and the edges that used to be silent holes: inbox tasks
must never be mistaken for study targets, completed rows must never pull focus,
and an old note must stop nagging.
"""
import time
import unittest
from datetime import datetime, timedelta

from litebrowser.core import prefs
from litebrowser.services import (
    flashcard_service,
    focus_service,
    life_service,
    link_service,
    personal_plan,
    personal_service,
    study_flow,
)

import os
import tempfile


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def _flow(self) -> dict:
        return study_flow.build_flow(self.base)

    def _next(self) -> dict:
        return study_flow.next_step(self.base)


class TestStepLadder(_Base):
    def test_empty_profile_invites_a_week_plan(self):
        action = self._next()
        self.assertEqual(action["step"], "plan")
        self.assertIn("Plan your week", action["label"])
        self.assertFalse(action["start"])
        self.assertEqual(action["id"], "")

    def test_running_pour_outranks_every_other_signal(self):
        item = personal_plan.create_item(self.base, "Late essay", due_date=_days_ago(3))
        flashcard_service.add_card(self.base, "Q", "A")
        focus_service.start_focus(self.base, minutes=25, label="Deep work")
        action = self._next()
        self.assertEqual(action["step"], "study")
        self.assertFalse(action["start"], "the running pour must be finished, not restarted")
        self.assertIn("Finish your pour", action["label"])
        self.assertTrue(item["id"])  # the overdue item is still there, just not first

    def test_overdue_planner_item_beats_today_and_cards(self):
        personal_plan.create_item(self.base, "Today's reading", scheduled_date=_today())
        flashcard_service.add_card(self.base, "Q", "A")
        late = personal_plan.create_item(self.base, "Late essay", due_date=_days_ago(3), duration_minutes=30)
        action = self._next()
        self.assertEqual(action["step"], "study")
        self.assertEqual(action["id"], late["id"])
        self.assertEqual(action["kind"], "planner-item")
        self.assertEqual(action["minutes"], 30)
        self.assertTrue(action["start"])
        self.assertIn("Overdue", action["reason"])

    def test_today_beats_blocks_and_cards(self):
        personal_plan.create_time_block(self.base, "Block", _today(), 540)
        flashcard_service.add_card(self.base, "Q", "A")
        today_item = personal_plan.create_item(self.base, "Read ch.4", scheduled_date=_today())
        action = self._next()
        self.assertEqual(action["id"], today_item["id"])
        self.assertIn("Due today", action["reason"])

    def test_block_beats_cards_when_nothing_is_scheduled_as_an_item(self):
        block = personal_plan.create_time_block(self.base, "Focus block", _today(), 540, duration_minutes=90)
        flashcard_service.add_card(self.base, "Q", "A")
        action = self._next()
        self.assertEqual(action["step"], "study")
        self.assertEqual(action["kind"], "planner-block")
        self.assertEqual(action["id"], block["id"])
        self.assertEqual(action["minutes"], 90)

    def test_cards_beat_the_inbox(self):
        flashcard_service.add_card(self.base, "Q", "A")
        life_service.add_task(self.base, "Buy milk", bucket="today")
        action = self._next()
        self.assertEqual(action["step"], "review")
        self.assertIn("1 due card", action["label"])

    def test_overdue_inbox_task_is_a_planning_problem_not_a_pour(self):
        task = life_service.add_task(self.base, "Old errand", due_at=int(time.time()) - 3 * 86400)
        action = self._next()
        self.assertEqual(action["step"], "plan")
        self.assertEqual(action["kind"], "task")
        self.assertEqual(action["id"], task["id"])
        self.assertFalse(action["start"], "an inbox task has no planner item to credit")
        self.assertIn("promote", action["reason"].lower())

    def test_fresh_capture_asks_for_cards(self):
        note = personal_service.create_note(self.base, "OSI Model", "# OSI\n\n7 layers")
        action = self._next()
        self.assertEqual(action["step"], "capture")
        self.assertEqual(action["kind"], "note")
        self.assertEqual(action["id"], note["id"])
        self.assertIn("into cards", action["label"])

    def test_a_note_with_cards_stops_nagging(self):
        note = personal_service.create_note(self.base, "OSI Model", "# OSI\n\n7 layers")
        flashcard_service.add_card(self.base, "Layers?", "7", source_note_id=note["id"])
        action = self._next()
        # The card is due, so the loop moves to Review rather than back to Capture.
        self.assertEqual(action["step"], "review")

    def test_an_old_uncarded_note_is_left_alone(self):
        note = personal_service.create_note(self.base, "Old note", "body")
        path = note["path"]
        old = time.time() - (study_flow.CAPTURE_WINDOW_DAYS + 5) * 86400
        os.utime(path, (old, old))
        action = self._next()
        self.assertEqual(action["step"], "plan")
        self.assertIn("Plan your week", action["label"])

    def test_brief_notes_are_not_study_material(self):
        today = study_flow.BRIEF_CATEGORY
        note = personal_service.create_note(self.base, "Morning Brief — today", "digest", category=today)
        self.assertTrue(note["id"])
        self.assertEqual(self._next()["step"], "plan")

    def test_completed_rows_never_pull_focus(self):
        item = personal_plan.create_item(self.base, "Done already", due_date=_days_ago(4))
        personal_plan.complete_item(self.base, item["id"], True)
        self.assertEqual(self._next()["step"], "plan")

    def test_unknown_entity_reference_degrades_to_the_default(self):
        """A stale agenda row (deleted between read and click) cannot wedge the loop."""
        item = personal_plan.create_item(self.base, "Ghost", due_date=_today())
        stale = {
            "kind": "planner-item",
            "id": item["id"],
            "title": "Ghost",
            "source": "planner",
            "subtitle": "",
            "overdue": False,
        }
        personal_plan.delete_item(self.base, item["id"])
        action = study_flow._study_action(self.base, stale, "Due today")
        self.assertEqual(action["minutes"], personal_plan.DEFAULT_DURATION_MINUTES)


class TestBuildFlow(_Base):
    def test_steps_follow_the_declared_order(self):
        flow = self._flow()
        self.assertEqual([step["key"] for step in flow["steps"]], [step["key"] for step in study_flow.FLOW_STEPS])
        self.assertEqual(
            [step["key"] for step in flow["steps"]], ["capture", "plan", "study", "review", "reflect"]
        )
        for step in flow["steps"]:
            with self.subTest(step=step["key"]):
                self.assertTrue(step["title"])
                self.assertTrue(step["blurb"])
                self.assertIsInstance(step["count"], int)
                self.assertTrue(step["detail"])
                self.assertEqual(step["ready"], step["count"] > 0)

    def test_counts_read_every_store(self):
        personal_plan.create_item(self.base, "Unscheduled", kind="assignment")
        life_service.add_task(self.base, "Inbox row", bucket="today")
        personal_plan.create_item(self.base, "Studied", scheduled_date=_today(), studied_minutes=30)
        flashcard_service.add_card(self.base, "Q", "A")
        note = personal_service.create_note(self.base, "Capture me", "body")
        card = flashcard_service.add_card(self.base, "Linked", "A", source_note_id=note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"])

        flow = self._flow()
        counts = flow["counts"]
        self.assertEqual(counts["plan"], 2, "one unscheduled item + one inbox task")
        self.assertEqual(counts["study"], 1, "only the item with no credit counts")
        self.assertEqual(counts["review"], 2)
        self.assertEqual(counts["capture"], 0, "the only fresh note already has a card")
        self.assertEqual(counts["reflect"], 1)
        self.assertEqual(flow["steps"][2]["detail"], "1 item(s) never studied")
        self.assertEqual(flow["steps"][3]["detail"], "2 card(s) due")

    def test_pulse_reports_the_day_then_the_next_step(self):
        personal_plan.create_item(self.base, "Late essay", due_date=_days_ago(2))
        personal_plan.create_item(self.base, "Read ch.4", scheduled_date=_today())
        flashcard_service.add_card(self.base, "Q", "A")
        flow = self._flow()
        self.assertIn("1 overdue", flow["pulse"])
        self.assertIn("2 planned today", flow["pulse"])
        self.assertIn("1 card(s) due", flow["pulse"])
        self.assertIn("next: ▶ Study “Late essay”", flow["pulse"])

    def test_pulse_of_an_empty_profile_is_calm(self):
        flow = self._flow()
        self.assertIn("Nothing due", flow["pulse"])
        self.assertIn("next:", flow["pulse"])

    def test_focus_minutes_land_in_the_pulse(self):
        focus_service.start_focus(self.base, minutes=25)
        flow = self._flow()
        self.assertEqual(flow["focus_minutes"], 0, "a pour that has not ended is not minutes yet")
        self.assertEqual(self._next()["step"], "study")

    def test_flow_is_a_report_only_no_writes(self):
        item = personal_plan.create_item(self.base, "Watch me")
        before = open(personal_plan.plan_path(self.base), encoding="utf-8").read()
        study_flow.build_flow(self.base)
        self.assertEqual(open(personal_plan.plan_path(self.base), encoding="utf-8").read(), before)
        self.assertEqual(len(personal_plan.load_plan(self.base)["items"]), 1)
        self.assertEqual(item["title"], "Watch me")


class TestPromoteTask(_Base):
    def setUp(self):
        super().setUp()
        self.task = life_service.add_task(self.base, "Write lab report", bucket="study")

    def test_promote_moves_the_capture_into_the_planner(self):
        item = study_flow.promote_task(self.base, self.task["id"])
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "Write lab report")
        self.assertEqual(item["kind"], "task")
        stored = personal_plan.load_plan(self.base)["items"]
        self.assertEqual([row["id"] for row in stored], [item["id"]])

    def test_promote_keeps_both_sides_linked(self):
        item = study_flow.promote_task(self.base, self.task["id"])
        task_links = link_service.links_for(self.base, "task", self.task["id"])
        item_links = link_service.links_for(self.base, "planner_item", item["id"])
        self.assertEqual(task_links["total"], 1)
        self.assertEqual(item_links["total"], 1, "the same row resolves from both ends")
        self.assertEqual(task_links["outgoing"][0]["label"], "promoted")
        self.assertEqual(item_links["incoming"][0]["from_id"], self.task["id"])

    def test_promote_clears_the_inbox_row_from_the_agenda(self):
        life_service.add_task(self.base, "Other errand", bucket="today")
        study_flow.promote_task(self.base, self.task["id"])
        agenda_titles = [entry["title"] for entry in life_service.today_agenda(self.base)["items"]]
        self.assertNotIn("Write lab report", agenda_titles)
        # The row is completed, not deleted: un-ticking it brings it back.
        life_service.toggle_task(self.base, self.task["id"])
        self.assertIn("Write lab report", [t["title"] for t in life_service.load_tasks(self.base)])

    def test_promoted_item_carries_the_due_date(self):
        task = life_service.add_task(self.base, "Dated", due_at=int(time.time()) + 86400)
        item = study_flow.promote_task(self.base, task["id"])
        expected = datetime.fromtimestamp(int(task["due_at"])).strftime("%Y-%m-%d")
        self.assertEqual(item["due_date"], expected)
        self.assertEqual(item["scheduled_date"], expected)

    def test_promote_without_a_date_stays_unscheduled(self):
        # The fixture task is filed under "study", so it has no day of its own.
        item = study_flow.promote_task(self.base, self.task["id"])
        self.assertEqual(item["due_date"], "")
        self.assertEqual(item["scheduled_date"], "")
        # and that lands it in the plan counter, not on the agenda
        self.assertEqual(self._flow()["counts"]["plan"], 1)
        self.assertEqual(life_service.today_agenda(self.base)["counts"]["planner"], 0)

    def test_a_today_bucket_capture_lands_on_todays_plan(self):
        """Promoting must not move a row out of the only list that showed it."""
        task = life_service.add_task(self.base, "Summarise notes", bucket="today")
        item = study_flow.promote_task(self.base, task["id"])
        self.assertEqual(item["due_date"], _today())
        agenda = life_service.today_agenda(self.base)
        self.assertEqual(agenda["counts"]["planner"], 1)
        self.assertEqual(agenda["counts"]["inbox"], 0)
        self.assertEqual(agenda["items"][0]["id"], item["id"])

    def test_explicit_due_date_wins(self):
        item = study_flow.promote_task(self.base, self.task["id"], due_date="2027-01-04")
        self.assertEqual(item["due_date"], "2027-01-04")

    def test_repeated_promote_links_twice_and_dedupes_the_activity_event(self):
        first = study_flow.promote_task(self.base, self.task["id"])
        second = study_flow.promote_task(self.base, self.task["id"])
        # A second call promotes the same capture again — the inbox row is
        # durable — but both items must point back at the one task.
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(link_service.links_for(self.base, "task", self.task["id"])["total"], 2)
        events = [
            event
            for event in study_flow.history_service.load_activity(self.base)["events"]
            if event["kind"] == "plan"
        ]
        # history_service suppresses consecutive identical events inside 2 s, so
        # a double click cannot spam the activity log.
        self.assertEqual(len(events), 1)
        self.assertIn("Promoted inbox task", events[0]["detail"])
        # The surviving event is the first one (the second was suppressed), so it
        # still names the item the row was promoted to the first time.
        self.assertEqual(events[0]["meta"]["item_id"], first["id"])

    def test_unknown_task_is_a_no_op(self):
        self.assertIsNone(study_flow.promote_task(self.base, "nope"))
        self.assertEqual(personal_plan.load_plan(self.base)["items"], [])
        self.assertEqual(link_service.load_links(self.base), [])

    def test_a_completed_task_is_not_promoted_twice_into_the_agenda(self):
        study_flow.promote_task(self.base, self.task["id"])
        self.assertEqual(life_service.today_agenda(self.base)["counts"]["inbox"], 0)
        self.assertEqual(self._next()["step"], "plan", "nothing is due; the loop asks for a plan")


if __name__ == "__main__":
    unittest.main()
