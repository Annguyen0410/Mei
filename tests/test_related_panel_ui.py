"""Note “Related” panel + planner routing, exercised on a real offscreen window.

Covers the desktop wiring for the entity-link store: the panel lists both
directions, double-click routes to the planner, Unlink removes the edge, and
open_plan_item lands on the item's week with its row selected.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt shim

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from litebrowser.core import prefs
from litebrowser.services import link_service, personal_plan, personal_service
from litebrowser.ui import personal_window as _pw_module  # noqa: F401 - QtWebEngine before QApplication


@unittest.skipUnless(sys.platform.startswith("win"), "offscreen smoke on dev machine")
class TestRelatedPanelUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self._patched = []
        self.window = None

    def tearDown(self):
        import litebrowser.ui.personal_window as pw

        for attr, value in self._patched:
            setattr(pw, attr, value)
        if self.window is not None:
            self.window.close()
        self._tmp.cleanup()

    def _window(self):
        from PyQt5.QtWidgets import QWidget

        import litebrowser.ui.personal_window as pw

        class _FakeSiteView(QWidget):
            def __getattr__(self, name):
                return lambda *a, **k: None

        self._patched.append(("_build_site_view", pw.PersonalWindow._build_site_view))
        pw.PersonalWindow._build_site_view = lambda self: _FakeSiteView()
        self.window = pw.PersonalWindow(self.base, embedded=True)
        return self.window

    def test_related_panel_lists_routes_and_unlinks(self):
        win = self._window()
        note = personal_service.create_note(self.base, "OSI Model", "7 layers")
        item = personal_plan.create_item(self.base, "Ôn chương 3", scheduled_date="2026-09-08")
        win._refresh_notes()
        win.select_note(note["id"])
        self.assertEqual(win.links_list.count(), 0)

        link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])
        win._refresh_entity_links()
        self.assertEqual(win.links_list.count(), 1)
        row = win.links_list.item(0)
        self.assertIn("Ôn chương 3", row.text())
        self.assertEqual(row.data(Qt.UserRole)["kind"], "planner_item")

        # Double-click jumps to the Weekly Plan on that item's week.
        win._open_entity_link(row)
        self.assertEqual(win.stack.currentIndex(), win.page_order["plan"])
        self.assertEqual(win._planner_week_start, "2026-09-07")

        # Unlink removes the edge and hides the list again.
        win._switch_page("notes")
        win.links_list.setCurrentItem(row)
        win._remove_note_link()
        self.assertEqual(link_service.load_links(self.base), [])
        self.assertEqual(win.links_list.count(), 0)
        self.assertFalse(win.links_list.isVisible())

    def test_open_plan_item_selects_the_row_on_its_week(self):
        win = self._window()
        item = personal_plan.create_item(self.base, "Late essay", due_date="2026-09-10")
        win.open_plan_item(item["id"])
        self.assertEqual(win.stack.currentIndex(), win.page_order["plan"])
        self.assertEqual(win._planner_week_start, "2026-09-07")

        selected = ""
        for _label, day_list in win.plan_day_lists.values():
            row = day_list.currentItem()
            if row is not None:
                selected = str(row.data(Qt.UserRole) or "")
        self.assertEqual(selected, item["id"])


if __name__ == "__main__":
    unittest.main()
