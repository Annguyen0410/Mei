"""The shell must hand shared dialogs a parent they can actually read.

``show_routines_dialog`` and ``show_export_dialog`` were written for
``SearchWindow`` and read ``parent.base_dir``.  The shell's ``/routines`` and
``/export`` commands passed ``self`` (an ``AppShell``, which only ever had
``profile_dir``), so both raised AttributeError *inside a Qt slot* — and PyQt6
answers an unhandled exception there with qFatal, taking the application down
with no traceback.

The shell is too heavy to construct in this suite (WebEngine), so the contract
is pinned two ways: the attribute wiring in ``AppShell.__init__`` is asserted
from source, and both dialogs are built against a shell-shaped parent.
"""
import inspect
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from litebrowser.core import prefs
from litebrowser.services import routines_service
from litebrowser.ui.app_shell import AppShell
from litebrowser.ui.dialogs import navigation

_app = QApplication.instance() or QApplication([])


class _ShellParent(QWidget):
    """Just the surface a shared dialog touches on its parent."""

    def __init__(self, base_dir):
        super().__init__()
        self.profile_dir = base_dir
        self.base_dir = base_dir


class TestShellDialogContract(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.parent = _ShellParent(self.base)
        self.dialogs = []

    def tearDown(self):
        self.parent.deleteLater()
        self._tmp.cleanup()

    def _exec_recorder(self):
        def _exec(dialog):
            self.dialogs.append(dialog)
            QApplication.processEvents()
            return QDialog.Rejected

        return _exec

    def test_app_shell_initializes_base_dir_from_the_profile(self):
        source = inspect.getsource(AppShell.__init__)
        self.assertIn("self.base_dir = self.profile_dir", source)

    def test_routines_dialog_builds_against_a_shell_shaped_parent(self):
        routines_service.add_routine(
            self.base, "Morning brief", "09:30", [0, 1, 2], ["/brief"]
        )
        with mock.patch.object(QDialog, "exec", self._exec_recorder()):
            navigation.show_routines_dialog(self.parent)
        self.assertEqual(1, len(self.dialogs))
        dialog = self.dialogs[0]
        self.assertIn("Routines", dialog.windowTitle())
        self.assertTrue(dialog.findChildren(QPushButton))

    def test_export_dialog_builds_against_a_shell_shaped_parent(self):
        with mock.patch.object(QDialog, "exec", self._exec_recorder()):
            navigation.show_export_dialog(self.parent)
        self.assertEqual(1, len(self.dialogs))
        dialog = self.dialogs[0]
        self.assertIn("Export", dialog.windowTitle())
        labels = [button.text().lower() for button in dialog.findChildren(QPushButton)]
        self.assertTrue(any("markdown" in label for label in labels))
        self.assertTrue(any("html" in label for label in labels))

    def test_a_parent_without_base_dir_is_the_regression_we_fixed(self):
        """Documents the failure mode: the old call would raise, not render."""
        bare = QWidget()
        try:
            with self.assertRaises(AttributeError):
                navigation.show_routines_dialog(bare)
        finally:
            bare.deleteLater()


if __name__ == "__main__":
    unittest.main()
