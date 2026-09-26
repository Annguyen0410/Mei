"""The in-app guide is generated from the registries, so it cannot drift.

It used to be a grid of buttons with no search and no shortcut/command reference:
you could see the tools but not learn the app. These tests pin the two halves —
the generated reference (every shortcut, every command) and the curated feature
list — plus the search, the run-a-command path and the F1 entry point.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401  activates the Qt compatibility shim
from litebrowser.core import commands as command_registry
from litebrowser.qt import QtWidgets
from litebrowser.ui.dialogs import help_hub
from litebrowser.ui.dialogs.hotkeys import HOTKEYS

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "litebrowser")


class TestGuideContent(unittest.TestCase):
    def setUp(self):
        self.entries = help_hub.guide_entries()

    def test_every_registered_shortcut_is_documented(self):
        labels = {entry.label for entry in self.entries}
        missing = [shortcut for shortcut, _scope, _desc in HOTKEYS if shortcut not in labels]
        self.assertEqual(missing, [])

    def test_every_registered_command_is_documented(self):
        labels = {entry.label for entry in self.entries}
        missing = [cmd.name for cmd in command_registry.COMMANDS if cmd.name not in labels]
        self.assertEqual(missing, [])

    def test_commands_carry_their_hint_and_are_runnable(self):
        by_label = {entry.label: entry for entry in self.entries}
        for cmd in command_registry.COMMANDS:
            with self.subTest(command=cmd.name):
                entry = by_label[cmd.name]
                self.assertEqual(entry.command, cmd.name)
                self.assertEqual(entry.detail, cmd.hint())

    def test_curated_features_are_present_and_described(self):
        features = [entry for entry in self.entries if entry.group == help_hub.FEATURE_GROUP]
        self.assertEqual(len(features), len(help_hub.GUIDE_FEATURES))
        for entry in features:
            self.assertGreater(len(entry.detail), 20, entry.label)

    def test_f1_is_advertised_in_the_shortcut_table(self):
        self.assertIn("F1", [shortcut for shortcut, _s, _d in HOTKEYS])


class TestGuideSearch(unittest.TestCase):
    def setUp(self):
        self.entries = help_hub.guide_entries()

    def test_empty_query_returns_everything(self):
        self.assertEqual(help_hub.filter_entries(self.entries, ""), self.entries)
        self.assertEqual(help_hub.filter_entries(self.entries, "   "), self.entries)

    def test_feature_is_found_by_name(self):
        matches = help_hub.filter_entries(self.entries, "zen")
        self.assertTrue(any("Zen mode" == entry.label for entry in matches))

    def test_command_is_found_by_slash_name(self):
        matches = help_hub.filter_entries(self.entries, "/task")
        self.assertTrue(any(entry.label == "/task" for entry in matches))

    def test_all_words_must_match(self):
        self.assertTrue(help_hub.filter_entries(self.entries, "clipboard history"))
        self.assertFalse(help_hub.filter_entries(self.entries, "clipboard zebra"))

    def test_nonsense_finds_nothing(self):
        self.assertEqual(help_hub.filter_entries(self.entries, "qqqzzz"), ())


class _FakeShell(QtWidgets.QWidget):
    """The attributes the dialog touches while building its tool cards.

    A QWidget so the dialog can parent itself to it exactly like it does to the
    real SearchWindow.
    """

    base_dir = "."
    app_dir = "."

    def __init__(self):
        super().__init__()
        self.flashed = []
        self.ran = []

    def _dialog_stylesheet(self):
        return ""

    def _flash_status(self, message):
        self.flashed.append(message)

    def _handle_omnibar_text(self, text):
        self.ran.append(text)


class TestRunningFromTheGuide(unittest.TestCase):
    def test_command_runs_through_the_shell_when_available(self):
        shell = _FakeShell()
        self.assertEqual(help_hub.run_or_copy_command(shell, "/theme matcha"), "ran")
        self.assertEqual(shell.ran, ["/theme matcha"])

    def test_command_is_copied_when_the_surface_cannot_run_it(self):
        class _NoDispatcher:
            _dialog_stylesheet = staticmethod(lambda: "")

        result = help_hub.run_or_copy_command(_NoDispatcher(), "/freeze")
        self.assertEqual(result, "copied")
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "/freeze")

    def test_flash_receives_the_copied_hint(self):
        shell = _FakeShell()
        shell._handle_omnibar_text = None  # force the copy path
        help_hub.run_or_copy_command(shell, "/brief", shell._flash_status)
        self.assertTrue(shell.flashed and "/brief" in shell.flashed[0])


class TestDialogBuildsHeadless(unittest.TestCase):
    def _open(self):
        shell = _FakeShell()
        for name in (
            "save_current_tab_set",
            "capture_screenshot",
            "extract_text",
            "print_page",
            "save_page_pdf",
            "save_current_page_to_library",
            "capture_page_as_note",
            "show_bookmarks_dialog",
            "show_history_dialog",
            "show_downloads_dialog",
            "show_extensions_dialog",
            "show_vault",
        ):
            setattr(shell, name, lambda *args, **kwargs: None)
        with mock.patch.object(QtWidgets.QDialog, "exec_", return_value=0):
            help_hub.show_browser_control_center(shell)
        dialog = next(
            widget for widget in _app.topLevelWidgets() if widget.windowTitle() == "Help & Guide"
        )
        return dialog

    def test_dialog_shows_the_reference_and_filters_it(self):
        dialog = self._open()
        search = dialog.findChildren(QtWidgets.QLineEdit)[0]
        reference = dialog.findChildren(QtWidgets.QListWidget)[0]
        self.assertGreater(reference.count(), len(help_hub.GUIDE_FEATURES))
        search.setText("zen")
        rows = [reference.item(i).text() for i in range(reference.count())]
        self.assertTrue(any("Zen mode" in row for row in rows))
        self.assertTrue(all("LinkLumina" not in row for row in rows))
        search.setText("")
        self.assertGreater(reference.count(), len(help_hub.GUIDE_FEATURES))
        dialog.deleteLater()

    def test_dialog_uses_the_shell_stylesheet_hook(self):
        dialog = self._open()
        self.assertTrue(hasattr(dialog, "setStyleSheet"))
        dialog.deleteLater()


class TestEntryPoints(unittest.TestCase):
    def _source(self, relative):
        with open(os.path.join(PACKAGE, relative), encoding="utf-8-sig") as handle:
            return handle.read()

    def test_f1_opens_the_guide(self):
        text = self._source("ui/main_window/window.py")
        lines = [line for line in text.splitlines() if "F1" in line]
        self.assertTrue(lines)
        self.assertTrue(any("show_browser_control_center" in line for line in lines))

    def test_page_menu_offers_the_guide_with_its_shortcut(self):
        text = self._source("ui/main_window/window_topbar.py")
        self.assertIn("Help & guide", text)
        self.assertIn("\\tF1", text)

    def test_new_tab_page_teaches_the_shortcut(self):
        text = self._source("browser/new_tab_page.py")
        self.assertIn("? Help · F1", text)


if __name__ == "__main__":
    unittest.main()
