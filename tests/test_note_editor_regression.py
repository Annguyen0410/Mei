"""v6.5 regression: note editor must survive list refresh (data-loss fix)."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QtWebEngine must be imported BEFORE QApplication is created (Qt hard
# requirement) — personal_window pulls it in transitively.
from litebrowser.ui import personal_window as _pw_module  # noqa: E402,F401

from PyQt5.QtWidgets import QApplication  # noqa: E402

from litebrowser.core import prefs  # noqa: E402
from litebrowser.services import personal_service  # noqa: E402


@unittest.skipUnless(sys.platform.startswith("win"), "offscreen smoke on dev machine")
class TestNoteEditorSurvivesRefresh(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self._patched = []

    def tearDown(self):
        # Restore any patched symbols before the temp dir goes away.
        import litebrowser.ui.personal_window as pw

        for attr, value in self._patched:
            setattr(pw, attr, value)
        self._tmp.cleanup()

    def _window(self):
        import litebrowser.ui.personal_window as pw
        from PyQt5.QtWidgets import QWidget

        # Stub the site preview builder: constructing real WebEngine objects
        # in offscreen mode spawns Chromium and hangs; the Sites page is not
        # under test here.
        class _FakeSiteView(QWidget):
            def __getattr__(self, name):
                return lambda *a, **k: None

        self._patched.append(("_build_site_view", pw.PersonalWindow._build_site_view))
        pw.PersonalWindow._build_site_view = lambda self: _FakeSiteView()

        win = pw.PersonalWindow(self.base, embedded=True)
        return win

    def test_refresh_keeps_open_note_and_content(self):
        win = self._window()
        note = personal_service.create_note(self.base, "Alpha", "# Alpha\n\nbody", category="General")
        win._refresh_notes()
        win.select_note(note["id"])
        self.assertEqual(win.current_note_id, note["id"])

        # Simulate the user typing (marks dirty + schedules autosave).
        win.note_editor.setPlainText("# Alpha\n\nbody plus edits")
        self.assertTrue(win._note_dirty)

        # A search keystroke triggers _refresh_notes: the note must stay open.
        win.ed_note_search.setText("alp")
        win._notes_search_timer.start(); win._notes_search_timer.stop()  # emit timeout
        win._refresh_notes()  # what the debounce timer would run
        self.assertEqual(win.current_note_id, note["id"], "selection must survive refresh")
        self.assertIn("edits", win.note_editor.toPlainText())

    def test_move_notes_updates_open_note_id(self):
        win = self._window()
        note = personal_service.create_note(self.base, "Mover", "content", category="General")
        win._refresh_notes()
        win.select_note(note["id"])

        win._move_notes_to_category([note["id"]], "Work")
        new_note = personal_service.list_notes(self.base, "Mover")[0]
        self.assertEqual(win.current_note_id, new_note["id"], "open note must follow the moved file")
        # And a later save must succeed (v6.4 silently failed here).
        win.note_editor.setPlainText("updated body")
        win._save_note()
        saved = personal_service.read_note(self.base, win.current_note_id)
        self.assertEqual(saved["content"], "updated body")


if __name__ == "__main__":
    unittest.main()
