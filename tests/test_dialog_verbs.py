"""Dialog verbs: one filled action per dialog, the rest behind one menu.

Dialogs used to end in five to seven look-alike buttons, so the action the dialog
existed for was indistinguishable from "Delete everything" two pixels away. The
6.7 pass gave them a role-based footer (``ui/dialogs/common.py``): exactly one
accent-filled primary, at most two secondary ghosts, and one "⋯ More" overflow
menu for the occasional verbs.

This file keeps that shape from creeping back, and keeps the moved verbs
reachable — a rename that loses its menu entry is worse than a wall of buttons.
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

# QtWebEngine has to be imported before QApplication exists, or the interpreter
# dies with an access violation later in the run (no traceback).
from litebrowser.ui import personal_window as _pw_module  # noqa: F401 - QtWebEngine first
from litebrowser.ui import vault_ui
from litebrowser.ui.dialogs import navigation as nav_module
from litebrowser.ui.dialogs import profiles_privacy as pp_module
from litebrowser.ui.dialogs import sessions as sessions_module
from litebrowser.ui.dialogs import vpn_hub as vpn_module

_app = QApplication.instance() or QApplication([])


class _TabManager:
    def add_tab(self, *_args, **_kwargs):
        return None


class _DialogParent(QWidget):
    """Just enough host for the dialogs these tests open."""

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.ext_path = os.path.join(base_dir, "ext")
        self.tab_manager = _TabManager()

    def _dialog_stylesheet(self):
        from litebrowser.ui import theme

        return theme.dialog_qss()

    def _refreshed(self, *_args, **_kwargs):
        return None


def _menu_labels(dialog) -> list:
    labels = []
    for button in dialog.findChildren(QPushButton):
        menu = button.menu()
        if menu is None:
            continue
        labels.extend(action.text() for action in menu.actions())
    return labels


def _menu_has(labels, needle: str) -> bool:
    """Menu verbs carry their glyph ("\U0001f5d1  Delete…"), so match on the verb."""
    return any(needle in label for label in labels)


class TestDialogVerbRoles(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.parent = _DialogParent(self.base)

    def tearDown(self):
        self.parent.deleteLater()

    def _capture(self, module, builder, *args):
        """Open a dialog with ``exec_`` stubbed: nothing is shown, nothing blocks."""
        captured = []

        def fake_exec(dialog, *_args, **_kwargs):
            captured.append(dialog)
            return 0

        with mock.patch.object(module.QDialog, "exec_", fake_exec):
            builder(self.parent, *args)
        self.assertTrue(captured, "the builder never reached exec_()")
        return captured[0]

    def _assert_shape(self, dialog, name):
        primaries = [b for b in dialog.findChildren(QPushButton) if b.objectName() == "PrimaryButton"]
        self.assertEqual(len(primaries), 1, f"{name}: one filled verb, got {len(primaries)}")
        overflow = [b for b in dialog.findChildren(QPushButton) if b.menu() is not None]
        self.assertTrue(overflow, f"{name}: the occasional verbs need an overflow menu")
        self.assertTrue(
            overflow[0].text().strip().startswith("⋯"),
            f"{name}: the overflow menu must read as one, not as a normal button",
        )
        # One primary, at most two secondaries, the menu owner, Close — anything
        # beyond that is a dialog growing back into a wall of buttons.
        self.assertLessEqual(len(dialog.findChildren(QPushButton)), 6, f"{name}: a wall of buttons")

    def test_vpn_hub_folds_probes_and_teardown_into_its_menu(self):
        # The hub starts a worker thread that calls a public IP API. Neither the
        # network nor a live QThread belongs in a suite that then keeps building
        # widgets (an unreaped probe thread is enough to take the run down): the
        # fetch is stubbed and the thread is never started.
        from PyQt5.QtCore import QThread

        with mock.patch.object(vpn_module, "_fetch_ip_info", return_value={}), mock.patch.object(
            QThread, "start", lambda self: None
        ):
            dialog = self._capture(vpn_module, vpn_module.show_vpn_hub)
        self._assert_shape(dialog, "vpn hub")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Run DNS leak test"))
        self.assertTrue(_menu_has(labels, "Load free proxies (HTTPS)"))
        self.assertTrue(_menu_has(labels, "Detailed form…"))
        # Disconnect stays a visible verb: it is the one people hunt for.
        texts = [b.text() for b in dialog.findChildren(QPushButton)]
        self.assertIn("Disconnect", texts)
        danger = [b for b in dialog.findChildren(QPushButton) if b.objectName() == "DangerButton"]
        self.assertEqual(len(danger), 1)

    def test_history_folds_its_four_delete_boxes_into_one_menu(self):
        dialog = self._capture(sessions_module, sessions_module.show_history_dialog)
        self._assert_shape(dialog, "history")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Delete everything"))
        self.assertTrue(_menu_has(labels, "Delete the last 24 hours"))

    def test_bookmarks_import_export_live_in_the_menu(self):
        dialog = self._capture(sessions_module, sessions_module.show_bookmarks_dialog)
        self._assert_shape(dialog, "bookmarks")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Import from file…"))
        self.assertTrue(_menu_has(labels, "Export as JSON"))

    def test_tab_sets_keeps_rename_and_delete_reachable(self):
        dialog = self._capture(sessions_module, sessions_module.show_tab_sets_dialog)
        self._assert_shape(dialog, "tab sets")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Rename…"))
        self.assertTrue(_menu_has(labels, "Delete this tab set"))

    def test_profiles_menu_still_creates_and_deletes(self):
        dialog = self._capture(pp_module, pp_module.show_profiles_dialog, self.base)
        self._assert_shape(dialog, "profiles")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Create a profile…"))
        self.assertTrue(_menu_has(labels, "Delete this profile"))

    def test_permissions_manager_folds_rule_bookkeeping_into_its_menu(self):
        dialog = self._capture(pp_module, pp_module.show_permissions_manager)
        self._assert_shape(dialog, "permissions")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Add a rule for a site…"))
        self.assertTrue(_menu_has(labels, "Reset every decision"))

    def test_workspace_menu_still_renames(self):
        dialog = self._capture(nav_module, nav_module.show_workspace_dialog)
        self._assert_shape(dialog, "workspaces")
        self.assertTrue(_menu_has(_menu_labels(dialog), "Rename the selected workspace…"))

    def test_routines_and_downloads_keep_their_verbs(self):
        routines = self._capture(nav_module, nav_module.show_routines_dialog)
        self._assert_shape(routines, "routines")
        self.assertTrue(_menu_has(_menu_labels(routines), "Remove the selected routine"))
        downloads = self._capture(nav_module, nav_module.show_downloads_dialog)
        self._assert_shape(downloads, "downloads")
        labels = _menu_labels(downloads)
        self.assertTrue(_menu_has(labels, "Remove from the list"))
        self.assertTrue(_menu_has(labels, "Reveal the file in its folder"))

    def test_feeds_dialog_keeps_unsubscribe_in_the_menu(self):
        dialog = self._capture(nav_module, nav_module.show_feeds_dialog)
        self._assert_shape(dialog, "feeds")
        self.assertTrue(_menu_has(_menu_labels(dialog), "Unsubscribe from the selected feed"))
        # The primary keeps Enter off only when a text field needs it; the feed
        # box subscribes on Return, so the dialog must not steal the key.
        self.assertFalse(
            any(
                b.objectName() == "PrimaryButton" and b.isDefault()
                for b in dialog.findChildren(QPushButton)
            )
        )

    def test_vault_keeps_new_note_and_folds_the_file_chores(self):
        dialog = self._capture(vault_ui, vault_ui.show_vault_dialog, os.path.join(self.base, "vault"), self.parent._dialog_stylesheet)
        self._assert_shape(dialog, "vault")
        labels = _menu_labels(dialog)
        self.assertTrue(_menu_has(labels, "Upload a file…"))
        self.assertTrue(_menu_has(labels, "Delete the selected item"))


if __name__ == "__main__":
    unittest.main()
