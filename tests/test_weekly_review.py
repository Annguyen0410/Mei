"""The reflect station: this week's numbers, and the loop's memoization.

`weekly_review` is the only place that answers "what did the week actually do?" —
minutes poured, the streak, and the rows nothing touched. This file pins that
digest, the Home card that renders it, and the memo that keeps the whole loop off
the GUI thread's critical path (including the part that matters: a write must
still be visible immediately).
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QWidget

from litebrowser.core import prefs
from litebrowser.services import (
    flashcard_service,
    focus_service,
    personal_plan,
    personal_service,
    study_flow,
)
from litebrowser.ui import personal_window as pw_module  # noqa: F401 - QtWebEngine first
from litebrowser.ui.shell import pages as pages_module

_app = QApplication.instance() or QApplication([])


class _StubShell(QWidget):
    """The shell surface Home touches while building and refreshing."""

    def __init__(self, base_dir, app_dir="."):
        super().__init__()
        self.profile_dir = base_dir
        self.app_dir = app_dir
        self.flow_steps = []
        self.browser_page = _StubBrowser()

    def switch_workspace(self, name):
        return True

    def open_flow_step(self, action):
        self.flow_steps.append(action)

    def refresh_shell(self, force_deep=False):
        return None

    def _flash_status(self, message):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _StubBrowser(QWidget):
    def get_current_tab_state(self):
        return []


class _ProfileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_pours(
        self,
        per_day: dict,
        item_id: str = "",
        label: str = "Pour",
        moment: datetime | None = None,
    ) -> None:
        """Write a journal as if ``per_day`` pours started ``{days_ago: minutes}``.

        Each pour is anchored just after its own midnight rather than at "now
        minus N days", because the journal files a pour under the day it
        *started* (``focus_service.compute_daily_minutes``): a 30-minute pour
        seeded at 00:19 on a UTC CI runner started at 23:49 the day before, so a
        one-day window counted nothing and the suite went red on a runner whose
        clock only agreed with mine for part of the day. ``moment`` moves the
        clock back to a suspicious hour on purpose (see the regression test).
        """
        midnight = (moment or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        sessions = []
        for index, (days_ago, minutes) in enumerate(per_day.items()):
            started = int((midnight - timedelta(days=int(days_ago)) + timedelta(minutes=2)).timestamp())
            sessions.append(
                {
                    "id": f"s{index}",
                    "label": label,
                    "minutes": int(minutes),
                    "started_at": started,
                    "ends_at": started + int(minutes) * 60,
                    "ended_at": started + int(minutes) * 60,
                    "status": "completed",
                    "item_id": item_id,
                    "credited": False,
                }
            )
        path = focus_service.sessions_path(self.base)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"active": None, "sessions": sessions}, handle)


class TestWeeklyDigest(_ProfileCase):
    def test_minutes_days_and_spark_come_from_the_journal(self):
        self._seed_pours({0: 25, 1: 50, 10: 60})
        review = study_flow.weekly_review(self.base)
        self.assertEqual(review["minutes_total"], 75)
        self.assertEqual(review["days_poured"], 2)
        self.assertEqual(review["days"], 7)
        self.assertEqual(len(review["spark"]), 7)
        self.assertGreaterEqual(review["streak"], 2)

    def test_an_old_pour_is_outside_the_window(self):
        self._seed_pours({0: 30, 10: 60})
        self.assertEqual(study_flow.weekly_review(self.base, days=1)["minutes_total"], 30)
        self.assertEqual(study_flow.weekly_review(self.base, days=30)["minutes_total"], 90)

    def test_a_pour_seeded_just_after_midnight_stays_on_its_own_day(self):
        """Regression: CI ran at 00:19 UTC, where a fifteen-to-thirty minute pour
        anchored at "now" belongs to yesterday and the one-day window read zero."""
        just_after_midnight = datetime.now().replace(hour=0, minute=19, second=0, microsecond=0)
        self._seed_pours({0: 30}, moment=just_after_midnight)
        self.assertEqual(study_flow.weekly_review(self.base, days=1)["minutes_total"], 30)
        started = focus_service.focus_journal(self.base)[0]["started_at"]
        self.assertEqual(datetime.fromtimestamp(started).date(), datetime.now().date())

    def test_a_window_with_no_pours_says_so(self):
        review = study_flow.weekly_review(self.base, days=7)
        self.assertEqual(review["minutes_total"], 0)
        self.assertIn("No pours yet this week", study_flow.review_line(review))

    def test_the_neglected_list_names_what_the_week_skipped(self):
        overdue = personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        personal_plan.create_item(self.base, "Read chapter 5", duration_minutes=40)
        personal_plan.complete_item(
            self.base, personal_plan.create_item(self.base, "Already done")["id"], True
        )
        review = study_flow.weekly_review(self.base)
        titles = [row["title"] for row in review["neglected"]]
        self.assertEqual(titles[0], "Late essay", "overdue work ranks first")
        self.assertIn("Read chapter 5", titles)
        self.assertNotIn("Already done", titles)
        self.assertTrue(review["neglected"][0]["detail"].startswith("overdue"))
        self.assertEqual(review["neglected"][0]["id"], overdue["id"])

    def test_an_item_that_was_studied_this_week_is_not_neglected(self):
        item = personal_plan.create_item(self.base, "Studied already", due_date="2020-01-01")
        self._seed_pours({1: 50}, item_id=item["id"])
        review = study_flow.weekly_review(self.base)
        self.assertEqual(review["neglected"], [])
        self.assertEqual(review["items_studied"], 1)
        self.assertIn("Nothing is being left behind", study_flow.review_line(review))

    def test_the_line_carries_the_spark_and_the_first_regret(self):
        self._seed_pours({0: 25})
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        line = study_flow.review_line(study_flow.weekly_review(self.base))
        self.assertIn("25 min in 7 days", line)
        self.assertIn("1/7 days poured", line)
        self.assertIn("Late essay", line)
        self.assertIn("▁", line, "the spark is a text chart, not a number")

    def test_the_review_is_a_line_per_idea_for_the_card(self):
        self._seed_pours({0: 25})
        review = study_flow.weekly_review(self.base)
        self.assertLessEqual(len(study_flow.review_line(review).splitlines()), 3)


class TestHomeReflectCard(_ProfileCase):
    def setUp(self):
        super().setUp()
        self.shell = _StubShell(self.base)
        self.page = pages_module.HomeDashboardPage(self.shell)

    def tearDown(self):
        self.page.deleteLater()
        self.shell.deleteLater()
        super().tearDown()

    def test_the_card_reports_the_week(self):
        self._seed_pours({0: 25})
        self.page.refresh()
        self.assertIn("25 min in 7 days", self.page.lbl_reflect.text())
        self.assertIn("poured", self.page.lbl_reflect.text())

    def test_the_card_lists_what_was_skipped(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        self.page.refresh()
        self.assertEqual(self.page.reflect_items.count(), 1)
        row = self.page.reflect_items.item(0)
        self.assertIn("Late essay", row.text())
        self.assertEqual(row.data(Qt.UserRole)["kind"], "planner-item")
        self.assertTrue(self.page.btn_reflect_study.isEnabled())

    def test_an_empty_week_says_so_instead_of_showing_nothing(self):
        self.page.refresh()
        self.assertEqual(self.page.reflect_items.count(), 1)
        self.assertIn("Nothing was skipped", self.page.reflect_items.item(0).text())
        self.assertFalse(self.page.btn_reflect_study.isEnabled())

    def test_study_the_oldest_one_routes_a_real_pour(self):
        item = personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        self.page.refresh()
        self.page._study_neglected()
        action = self.shell.flow_steps[-1]
        self.assertEqual(action["step"], "study")
        self.assertEqual(action["id"], item["id"])
        self.assertTrue(action["start"])

    def test_double_click_opens_the_planned_row(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        self.page.refresh()
        row = self.page.reflect_items.item(0)
        with mock.patch.object(self.shell, "open_library_item", create=True) as opener:
            self.page._open_reflect_item(row)
        self.assertEqual(opener.call_args[0][0]["id"], row.data(Qt.UserRole)["id"])


class TestLoopMemoization(_ProfileCase):
    """The memo is only safe if a write is still visible immediately."""

    def test_a_new_note_appears_without_waiting_for_the_ttl(self):
        note = personal_service.create_note(self.base, "Fresh clip", "body")
        self.assertEqual(study_flow.build_flow(self.base)["counts"]["capture"], 1)
        flashcard_service.add_card(self.base, "Q", "A", source_note_id=note["id"])
        self.assertEqual(study_flow.build_flow(self.base)["counts"]["capture"], 0)

    def test_a_new_deadline_moves_the_next_step(self):
        self.assertEqual(study_flow.next_step(self.base)["step"], "plan")
        item = personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        self.assertEqual(study_flow.next_step(self.base)["id"], item["id"])

    def test_a_warm_cache_does_not_touch_the_stores(self):
        study_flow.build_flow(self.base)
        with mock.patch.object(personal_plan, "load_plan", side_effect=RuntimeError("read the disk")):
            warm = study_flow.build_flow(self.base)
        self.assertIn("counts", warm)

    def test_the_memo_is_resettable_for_callers_that_must_see_the_truth(self):
        self.assertEqual(study_flow.build_flow(self.base)["counts"]["capture"], 0)
        personal_service.create_note(self.base, "Later clip", "body")
        study_flow.reset_flow_cache()
        self.assertEqual(study_flow.build_flow(self.base)["counts"]["capture"], 1)

    def test_a_caller_cannot_poison_the_cache(self):
        first = study_flow.build_flow(self.base)
        first["counts"]["capture"] = 999
        first["steps"].clear()
        second = study_flow.build_flow(self.base)
        self.assertEqual(second["counts"]["capture"], 0)
        self.assertEqual(len(second["steps"]), 5)


if __name__ == "__main__":
    unittest.main()
