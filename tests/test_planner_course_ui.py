"""Weekly Plan course picker + block editing, exercised on a real offscreen window.

The service-level course lifecycle is covered by test_personal_plan.py; this
file pins the desktop wiring that promoted those reserved APIs: the picker maps
a course to category/colour, and double-click editing writes back a block.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Activate the Qt shim before importing the binding (and before QApplication
# exists) — see test_note_editor_regression.py for the full rationale.
import litebrowser  # noqa: F401 - litebrowser/__init__ activates the Qt shim

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from litebrowser.core import prefs
from litebrowser.services import personal_plan
from litebrowser.ui import personal_window as _pw_module  # noqa: F401 - pulls QtWebEngine in before QApplication exists


@unittest.skipUnless(sys.platform.startswith("win"), "offscreen smoke on dev machine")
class TestPlannerCourseUI(unittest.TestCase):
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

        # Stub the site preview builder: constructing real WebEngine objects in
        # offscreen mode spawns Chromium and hangs; Sites is not under test.
        class _FakeSiteView(QWidget):
            def __getattr__(self, name):
                return lambda *a, **k: None

        self._patched.append(("_build_site_view", pw.PersonalWindow._build_site_view))
        pw.PersonalWindow._build_site_view = lambda self: _FakeSiteView()
        self.window = pw.PersonalWindow(self.base, embedded=True)
        return self.window

    def test_course_picker_tags_new_items(self):
        win = self._window()
        course = personal_plan.create_course(
            self.base, "Giải tích", code="MA101", color="#123456"
        )
        win._refresh_plan()
        combo = win.cmb_plan_course
        index = combo.findData(course["id"])
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)

        fields = win._planner_course_fields(combo)
        self.assertEqual(fields["course_id"], course["id"])
        self.assertEqual(fields["category"], "Giải tích")
        self.assertEqual(fields["color"], "#123456")

        win.ed_plan_title.setText("Ôn chương 3")
        win._planner_add_item()
        stored = personal_plan.load_plan(self.base)["items"][0]
        self.assertEqual(stored["course_id"], course["id"])
        self.assertEqual(stored["category"], "Giải tích")

    def test_course_list_shows_courses_and_edits_a_block(self):
        win = self._window()
        course = personal_plan.create_course(self.base, "Vật lý")
        block = personal_plan.create_time_block(self.base, "Tự học", personal_plan._today(), 540)
        win._refresh_plan()
        self.assertEqual(win.plan_courses_list.count(), 1)
        self.assertEqual(win.plan_courses_list.item(0).data(Qt.UserRole), course["id"])

        class _FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec_(self):
                from PyQt5.QtWidgets import QDialog

                return QDialog.Accepted

            def values(self):
                return {
                    "title": "Tự học 2",
                    "start_minutes": 600,
                    "duration_minutes": 90,
                    "course_id": course["id"],
                }

        import litebrowser.ui.personal_window as pw

        self._patched.append(("_BlockDialog", pw._BlockDialog))
        pw._BlockDialog = _FakeDialog
        win._planner_edit_block(block["id"])

        stored = personal_plan.load_plan(self.base)["time_blocks"][0]
        self.assertEqual(stored["title"], "Tự học 2")
        self.assertEqual(stored["duration_minutes"], 90)
        self.assertEqual(stored["course_id"], course["id"])


if __name__ == "__main__":
    unittest.main()
