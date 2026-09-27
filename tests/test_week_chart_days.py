"""The "Your Week" chart must count visits on the day they happened.

Reported from a screenshot that matched the *morning brief* but not the chart:
the brief said "9 pages yesterday", the chart showed 9 on today's bar, and the
40 visits from the day before sat under Thursday's label instead of Friday's.
The bucketing was ``(midnight_today - ts) // 86400``, and a visit made today is
after midnight, so the subtraction is negative, floor-divides to -1, and every
one of today's visits was dropped. Everything was a day late, and today was
always empty — on a chart whose whole job is "how much did I browse today".
"""
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The shim must be active before the binding is imported (see test_browser_topbar).
import litebrowser  # noqa: F401 - litebrowser/__init__ activates the Qt shim
from litebrowser.qt import QtWidgets

from litebrowser.core import prefs
from litebrowser.ui.shell.pages import _WeekActivityChart

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["mei-tests"])


def _noon(days_ago: int) -> float:
    """A timestamp at local noon, ``days_ago`` days back (DST-safe)."""
    return datetime.combine(date.today() - timedelta(days=days_ago), time(12, 0)).timestamp()


class TestWeekChartBucketsByCalendarDay(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="mei_weekchart_")
        self.base = os.path.join(self._tmp, "profile")
        prefs.ensure_profile_layout(self.base)
        self.chart = _WeekActivityChart(page=type("P", (), {"shell": type("S", (), {"profile_dir": self.base})()})())

    def _seed(self, day_counts):
        entries = []
        for days_ago, count in day_counts:
            entries.extend([(_noon(days_ago), f"https://example.com/{days_ago}-{i}") for i in range(count)])
        prefs.save_history_entries(self.base, entries)
        self.chart.refresh()
        return list(self.chart._counts)

    def test_todays_visits_land_on_todays_bar(self):
        counts = self._seed([(0, 3)])
        self.assertEqual(counts[6], 3, "today's visits are the one bar the user is standing on")
        self.assertEqual(counts[:6], [0] * 6)

    def test_each_day_keeps_its_own_bar(self):
        counts = self._seed([(0, 3), (1, 9), (2, 40)])
        self.assertEqual(counts, [0, 0, 0, 0, 40, 9, 3])

    def test_older_than_a_week_falls_out(self):
        counts = self._seed([(0, 1), (6, 5), (7, 7), (30, 99)])
        self.assertEqual(counts[6], 1)
        self.assertEqual(counts[0], 5)
        self.assertEqual(sum(counts), 6)

    def test_the_labels_end_on_today(self):
        self.chart.refresh()
        self.assertEqual(self.chart._day_labels[-1], date.today().strftime("%a"))
        self.assertEqual(
            self.chart._day_labels[0], (date.today() - timedelta(days=6)).strftime("%a")
        )

    def test_a_timestamp_that_cannot_be_a_date_is_skipped_not_fatal(self):
        prefs.save_history_entries(self.base, [(0, "https://example.com/zero"), (_noon(1), "https://example.com/one")])
        self.chart.refresh()
        self.assertEqual(list(self.chart._counts)[-1], 0)
        self.assertEqual(list(self.chart._counts)[-2], 1)


if __name__ == "__main__":
    unittest.main()
