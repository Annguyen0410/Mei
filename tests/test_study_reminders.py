"""Mei starts the loop: reminder rules, the pref that carries the gap, the tick.

The loop already knew the next step; this file pins the part that speaks first —
the three restraints (a running pour, the night, the gap), the honest
"nothing poured today" fallback, the preference that carries the interval, and
the timer the shell actually runs.
"""
import datetime as _dt
import os
import tempfile
import unittest
from unittest import mock

import litebrowser  # noqa: F401 - activates the Qt compatibility shim first
from litebrowser.qt import QtWidgets

from litebrowser.core import prefs
from litebrowser.services import focus_service, personal_plan, study_flow

QWidget = QtWidgets.QWidget

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _ProfileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _at(hour: int) -> float:
        """A timestamp today at ``hour`` so the rules never depend on when the suite runs."""
        today = _dt.date.today()
        return _dt.datetime.combine(today, _dt.time(hour, 0)).timestamp()

    def _pour_today(self, minutes: int = 25) -> None:
        """Put one *elapsed* pour in today's journal (what ``today_focus_seconds`` reads).

        Stopping a pour the instant it starts counts zero seconds, so the record is
        backdated exactly like a real 25-minute pour would look.
        """
        import json
        import time as _time

        focus_service.start_focus(self.base, minutes=minutes, label="Warm-up")
        focus_service.stop_focus(self.base, complete=True)
        path = focus_service.sessions_path(self.base)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        now = int(_time.time())
        for session in data.get("sessions", []):
            if session.get("label") == "Warm-up":
                session["started_at"] = now - minutes * 60
                session["ended_at"] = now
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)


class TestReminderRestraints(_ProfileCase):
    def test_an_overdue_deadline_is_worth_a_nudge(self):
        item = personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        nudge = study_flow.reminder(self.base, now=self._at(12))
        self.assertIsNotNone(nudge)
        self.assertEqual(nudge["step"], "study")
        self.assertEqual(nudge["id"], item["id"])
        self.assertIn("Late essay", nudge["message"])
        self.assertIn("Study", nudge["title"])

    def test_a_running_pour_is_never_interrupted(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        focus_service.start_focus(self.base, minutes=25, label="In progress")
        self.assertIsNone(study_flow.reminder(self.base, now=self._at(12)))

    def test_the_night_is_quiet(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        for hour in (23, 0, 3, 7):
            with self.subTest(hour=hour):
                self.assertIsNone(study_flow.reminder(self.base, now=self._at(hour)))

    def test_daytime_is_not_quiet(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        for hour in (8, 13, 21):
            with self.subTest(hour=hour):
                self.assertIsNotNone(study_flow.reminder(self.base, now=self._at(hour)))

    def test_the_gap_suppresses_a_second_nudge(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        noon = self._at(12)
        self.assertIsNone(
            study_flow.reminder(self.base, last_sent=noon - 10 * 60, min_gap_minutes=90, now=noon)
        )
        self.assertIsNotNone(
            study_flow.reminder(self.base, last_sent=noon - 3 * 3600, min_gap_minutes=90, now=noon)
        )

    def test_a_minimum_gap_is_enforced(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        noon = self._at(12)
        # A nonsense gap must not become "nudge every minute".
        self.assertIsNone(
            study_flow.reminder(self.base, last_sent=noon - 60, min_gap_minutes=0, now=noon)
        )


class TestReminderFallback(_ProfileCase):
    def test_a_clear_loop_asks_for_one_pour(self):
        nudge = study_flow.reminder(self.base, now=self._at(12))
        self.assertIsNotNone(nudge)
        self.assertEqual(nudge["step"], "study")
        self.assertEqual(nudge["id"], "")
        self.assertIn("Nothing poured today", nudge["title"])

    def test_a_clear_loop_stays_silent_once_something_was_poured(self):
        self._pour_today()
        self.assertIsNone(study_flow.reminder(self.base, now=self._at(12)))

    def test_due_cards_are_worth_a_nudge(self):
        from litebrowser.services import flashcard_service

        flashcard_service.add_card(self.base, "Q", "A")
        nudge = study_flow.reminder(self.base, now=self._at(12))
        self.assertIsNotNone(nudge)
        self.assertEqual(nudge["step"], "review")
        self.assertIn("card", nudge["message"])


class TestReminderPreference(_ProfileCase):
    def test_default_is_two_hours(self):
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 120)

    def test_value_round_trips(self):
        prefs.set_study_reminder_minutes(self.base, 30)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 30)
        prefs.set_study_reminder_minutes(self.base, 0)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 0)

    def test_values_are_clamped_and_junk_is_survivable(self):
        prefs.set_study_reminder_minutes(self.base, -5)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 0)
        prefs.set_study_reminder_minutes(self.base, 9999)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 480)
        prefs.set_study_reminder_minutes(self.base, "every so often")
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 120)


class TestShellWiring(unittest.TestCase):
    """The tick and the setting must exist in the shell, not only in the service."""

    def _source(self, relative: str) -> str:
        with open(os.path.join(ROOT, "litebrowser", relative), encoding="utf-8-sig") as handle:
            return handle.read()

    def test_shell_runs_the_reminder_timer(self):
        source = self._source("ui/app_shell.py")
        self.assertIn("_init_study_reminder", source)
        self.assertIn("study_flow.reminder(", source)
        self.assertIn("prefs.get_study_reminder_minutes(", source)

    def test_the_timer_is_started_at_launch(self):
        source = self._source("ui/app_shell.py")
        deferred = source.split("def _deferred_init", 1)[1].split("def _init_page_monitor", 1)[0]
        self.assertIn("_init_study_reminder()", deferred)

    def test_a_nudge_goes_through_the_native_toast_path(self):
        source = self._source("ui/app_shell.py")
        self.assertIn("self.system_notify(nudge.get", source)

    def test_settings_exposes_the_interval(self):
        source = self._source("ui/shell/pages.py")
        self.assertIn("cmb_study_reminder", source)
        self.assertIn("prefs.set_study_reminder_minutes(", source)


class _TickShell(QWidget):
    """The three attributes AppShell's reminder methods touch (no window built)."""

    def __init__(self, base_dir):
        super().__init__()
        self.profile_dir = base_dir
        self.notifications = []

    def system_notify(self, title, message):
        self.notifications.append((title, message))


class TestShellTick(unittest.TestCase):
    """The tick itself, executed: pref → service → toast.

    Deliberately driven through ``AppShell._check_study_reminder`` on a stub rather
    than a constructed shell: the method is the part that can silently stop
    nudging, and building QtWebEngine windows inside the suite is riskier than it
    is informative.
    """

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication

        from litebrowser.ui.app_shell import AppShell

        self._app = QApplication.instance() or QApplication(["mei-tests"])
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.shell = _TickShell(self.base)
        # The real AppShell methods, bound to the stub: the tick runs its own code.
        for name in ("_init_study_reminder", "_check_study_reminder"):
            setattr(self.shell, name, getattr(AppShell, name).__get__(self.shell))
        # One launch, like the shell does it: the gap only exists if the tick is
        # not re-initialised (re-initialising would reset the gap on every check).
        self.shell._init_study_reminder()

    def tearDown(self):
        self.shell.deleteLater()
        self._tmp.cleanup()

    def _tick(self):
        # The quiet window is a clock rule; pin it open so this test means the same
        # thing at 10:00 and at 23:00.
        before = len(self.shell.notifications)
        with mock.patch.object(study_flow, "REMINDER_QUIET_HOURS", (25, 26)):
            self.shell._check_study_reminder()
        return self.shell.notifications[before:]

    def test_one_tick_sends_the_next_step_as_a_toast(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        notifications = self._tick()
        self.assertEqual(len(notifications), 1)
        title, message = notifications[0]
        self.assertIn("Study", title)
        self.assertIn("Late essay", message)

    def test_the_tick_installs_a_timer(self):
        self.shell._init_study_reminder()
        self.assertTrue(self.shell._study_reminder_timer.isActive())
        self.assertEqual(self.shell._study_reminder_timer.interval(), 60 * 1000)

    def test_the_same_tick_stays_quiet_when_reminders_are_off(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        prefs.set_study_reminder_minutes(self.base, 0)
        self.assertEqual(self._tick(), [])

    def test_a_second_tick_inside_the_gap_is_silent(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        prefs.set_study_reminder_minutes(self.base, 120)
        self.assertEqual(len(self._tick()), 1)
        self.assertEqual(self._tick(), [])

    def test_a_broken_tick_cannot_kill_the_shell(self):
        self.shell._init_study_reminder()
        with mock.patch.object(study_flow, "reminder", side_effect=RuntimeError("boom")):
            self.shell._check_study_reminder()  # must not raise
        self.assertEqual(self.shell.notifications, [])


if __name__ == "__main__":
    unittest.main()
