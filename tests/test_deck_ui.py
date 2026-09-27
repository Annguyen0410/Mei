"""The Review page's deck file menu: two verbs, wired to the real service.

``test_anki_deck.py`` covers the package format itself; this file asks only
whether the *page* reaches the service. It exists because a rewritten control
row once kept two buttons that no layout ever showed — wired, connect()ed, and
impossible to click, which no service test can catch. So: the menu is reachable
in the page, its verbs hand the file dialogs' answers to ``anki_service``, and a
package that cannot be read raises a message instead of a traceback.
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The shim has to be active before the binding is imported.
import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtWidgets import QApplication, QWidget

from litebrowser.core import prefs
from litebrowser.services import anki_service, flashcard_service
from litebrowser.ui import personal_window as pw_module  # noqa: F401 - QtWebEngine first


class TestDeckFileMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.other = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "other"))
        self._patched = []

    def tearDown(self):
        for attr, value in self._patched:
            setattr(pw_module.PersonalWindow, attr, value)
        self._tmp.cleanup()

    def _window(self):
        """A PersonalWindow with the WebEngine site view stubbed out."""

        class _FakeSiteView(QWidget):
            def __getattr__(self, name):
                return lambda *args, **kwargs: None

        self._patched.append(("_build_site_view", pw_module.PersonalWindow._build_site_view))
        pw_module.PersonalWindow._build_site_view = lambda self: _FakeSiteView()
        return pw_module.PersonalWindow(self.base, embedded=True)

    @staticmethod
    def _trigger(button, needle: str) -> None:
        menu = button.menu()
        verbs = [action for action in (menu.actions() if menu else []) if needle in action.text()]
        assert verbs, f"no menu verb matching {needle!r}"
        verbs[0].trigger()

    def test_the_menu_is_reachable_and_carries_both_verbs(self):
        win = self._window()
        try:
            verbs = [action.text() for action in win.btn_deck_file.menu().actions()]
            self.assertIn("Import an Anki deck", " | ".join(verbs))
            self.assertIn("Export as an Anki deck", " | ".join(verbs))
            # The page's own widget tree has to contain it: a button nobody laid
            # out is exactly the failure this file exists for, and a stacked page
            # that is merely not the current one still counts as reachable.
            self.assertTrue(win.isAncestorOf(win.btn_deck_file))
            self.assertTrue(win.btn_deck_file.isEnabled())
            self.assertEqual(len(verbs), 2)
        finally:
            win.deleteLater()

    def test_importing_from_the_menu_adds_the_cards(self):
        flashcard_service.add_card(self.other, "Imported front", "Imported back")
        package = os.path.join(self._tmp.name, "other-deck.apkg")
        anki_service.export_package(self.other, package)
        win = self._window()
        try:
            with mock.patch.object(pw_module.QFileDialog, "getOpenFileName", return_value=(package, "")), \
                    mock.patch.object(pw_module.QMessageBox, "information") as told:
                self._trigger(win.btn_deck_file, "Import")
            self.assertEqual([c["front"] for c in flashcard_service.load_cards(self.base)], ["Imported front"])
            self.assertEqual(win.lbl_review_counter.text(), "1 / 1", "the page shows the imported card")
            self.assertIn("Imported 1 card from", told.call_args[0][2])
        finally:
            win.deleteLater()

    def test_exporting_from_the_menu_writes_a_package_anki_can_read(self):
        flashcard_service.add_card(self.base, "Front", "Back")
        target = os.path.join(self._tmp.name, "mei-deck.apkg")
        win = self._window()
        try:
            with mock.patch.object(pw_module.QFileDialog, "getSaveFileName", return_value=(target, "")), \
                    mock.patch.object(pw_module.QMessageBox, "information") as told:
                self._trigger(win.btn_deck_file, "Export")
            self.assertTrue(os.path.isfile(target))
            self.assertEqual(anki_service.import_package(self.other, target)["imported"], 1)
            self.assertIn("Exported 1 card to", told.call_args[0][2])
        finally:
            win.deleteLater()

    def test_a_cancelled_dialog_touches_nothing(self):
        win = self._window()
        try:
            with mock.patch.object(pw_module.QFileDialog, "getOpenFileName", return_value=("", "")), \
                    mock.patch.object(anki_service, "import_package") as importer:
                self._trigger(win.btn_deck_file, "Import")
            importer.assert_not_called()
        finally:
            win.deleteLater()

    def test_an_unreadable_package_reports_instead_of_crashing(self):
        broken = os.path.join(self._tmp.name, "broken.apkg")
        with open(broken, "wb") as handle:
            handle.write(b"not a zip")
        win = self._window()
        try:
            with mock.patch.object(pw_module.QFileDialog, "getOpenFileName", return_value=(broken, "")), \
                    mock.patch.object(pw_module.QMessageBox, "warning") as warned:
                self._trigger(win.btn_deck_file, "Import")
            self.assertIn("Import failed", warned.call_args[0][2])
            self.assertEqual(flashcard_service.load_cards(self.base), [])
        finally:
            win.deleteLater()


if __name__ == "__main__":
    unittest.main()
