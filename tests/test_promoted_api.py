"""Promoted capabilities: the ledger's §2 became screens.

`docs/CAPABILITIES.md` §2 is for API that is reachable but has no desktop caller.
Google sign-in, token refresh, the planner's term settings, the passcode re-lock,
watched-page removal and the two renames all used to live there; this file is what
keeps each of them *promoted* — a test fails if the screen (and therefore the
caller) disappears, and the two dialog paths are driven end to end offscreen.
"""
import os
import tempfile
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401 - activates the Qt compatibility shim

from PyQt5.QtWidgets import QApplication, QLineEdit, QListWidget, QPushButton, QWidget

from litebrowser.core import prefs
from litebrowser.services import (
    focus_service,  # noqa: F401 - keeps the import order of the app modules stable
    page_monitor,
    personal_plan,
    security,
    tab_sets,
    workspace_manager,
)
from litebrowser.ui import personal_window as pw_module  # noqa: F401 - QtWebEngine first
from litebrowser.ui.dialogs import navigation as nav_module
from litebrowser.ui.dialogs import sessions as sessions_module
from litebrowser.ui.shell import pages as pages_module

_app = QApplication.instance() or QApplication([])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def click_dialog_verb(dialog, label: str) -> bool:
    """Press a dialog verb by its label, whether it is a button or a menu entry.

    Dialogs fold their occasional verbs into one "⋯ More" menu (ui/dialogs/common.py),
    so a test that only walks QPushButton texts stops seeing Rename/Delete the day
    they move in there. Looking one level deeper keeps the test about the store
    write, not about where the button happens to sit.
    """
    for button in dialog.findChildren(QPushButton):
        if button.text() == label:
            button.click()
            return True
    for button in dialog.findChildren(QPushButton):
        menu = button.menu()
        if menu is None:
            continue
        for action in menu.actions():
            if action.text() == label:
                action.trigger()
                return True
    return False


class _ImmediateFuture:
    """Stands in for the executor's future: the work already ran."""

    def __init__(self, value, error=None):
        self._value = value
        self._error = error

    def result(self):
        if self._error is not None:
            raise self._error
        return self._value


class _StubShell(QWidget):
    """Everything SettingsPage reads, plus a synchronous background relay."""

    def __init__(self, base_dir, work=None):
        super().__init__()
        self.profile_dir = base_dir
        self.app_dir = "."
        self.update_status_text = ""
        self._pending_update_info = None
        self.browser_page = _StubBrowser()
        self.jobs = []

    def run_in_background(self, work, on_done=None):
        self.jobs.append(work)
        try:
            future = _ImmediateFuture(work())
        except Exception as exc:  # the real relay delivers failures too
            future = _ImmediateFuture(None, error=exc)
        if on_done is not None:
            on_done(future)
        return future

    def refresh_shell(self, force_deep=False):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _StubBrowser(QWidget):
    def current_browser(self):
        return None


class _ProfileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()


class TestCallersExist(unittest.TestCase):
    """Each promoted function must be named by the surface that promotes it."""

    CASES = (
        ("ui/shell/pages.py", "google_auth.sign_in_via_device_code"),
        ("ui/shell/pages.py", "google_auth.ensure_valid_token"),
        ("ui/shell/pages.py", "prefs.get_google_token_cache("),
        ("ui/shell/pages.py", "prefs.set_google_token_cache("),
        ("ui/shell/pages.py", "security.lock("),
        ("ui/shell/pages.py", "page_monitor.remove_monitor("),
        ("ui/shell/pages.py", "page_monitor.load_monitors("),
        ("ui/dialogs/navigation.py", "workspace_manager.rename_workspace("),
        ("ui/dialogs/sessions.py", "tab_sets.rename_tab_set("),
        ("ui/personal_window.py", "personal_plan.update_plan_settings("),
        ("ui/app_shell.py", "def run_in_background"),
    )

    def test_the_promoting_surface_calls_the_reserved_api(self):
        for relative, needle in self.CASES:
            with self.subTest(module=relative, needle=needle):
                with open(os.path.join(ROOT, "litebrowser", relative), encoding="utf-8-sig") as handle:
                    self.assertIn(needle, handle.read())

    def test_the_ledger_still_only_reserves_what_is_left(self):
        with open(os.path.join(ROOT, "docs", "CAPABILITIES.md"), encoding="utf-8") as handle:
            section = handle.read().split("## 2. Reserved API", 1)[1].split("## 3.", 1)[0]
        for promoted in (
            "update_plan_settings",
            "remove_monitor",
            "rename_tab_set",
            "rename_workspace",
            "sign_in_via_device_code",
            "ensure_valid_token",
            "get_google_token_cache",
            "security.lock",
        ):
            with self.subTest(promoted=promoted):
                self.assertNotIn(promoted, section, "promoted capability is still listed as reserved")
        self.assertIn("cuc_quan_ly_support_url", section)


class TestSettingsPromotions(_ProfileCase):
    def setUp(self):
        super().setUp()
        self.shell = _StubShell(self.base)
        self.page = pages_module.SettingsPage(self.shell)

    def tearDown(self):
        self.page.deleteLater()
        self.shell.deleteLater()
        super().tearDown()

    def test_the_reminder_combo_writes_the_preference(self):
        self.assertEqual(self.page.cmb_study_reminder.count(), 6)
        index = self.page.cmb_study_reminder.findData(60)
        self.page.cmb_study_reminder.setCurrentIndex(index)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 60)
        self.page.cmb_study_reminder.setCurrentIndex(self.page.cmb_study_reminder.findData(0))
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 0)

    def test_loading_the_page_does_not_overwrite_the_preference(self):
        prefs.set_study_reminder_minutes(self.base, 480)
        self.page.refresh()
        self.assertEqual(self.page.cmb_study_reminder.currentData(), 480)
        self.assertEqual(prefs.get_study_reminder_minutes(self.base), 480)

    def test_ledger_buttons_start_from_a_honest_state(self):
        self.page.refresh()
        self.assertFalse(self.page.btn_lock_now.isEnabled(), "no passcode set yet")
        self.assertFalse(self.page.google_sign_out_action.isEnabled())
        self.assertFalse(self.page.btn_monitor_remove.isEnabled())

    def test_watched_pages_can_be_removed(self):
        page_monitor.add_monitor(self.base, "https://example.com/watch", "Example")
        self.page.refresh()
        self.assertTrue(self.page.btn_monitor_remove.isEnabled())
        self.page.monitors_list.setCurrentRow(0)
        self.page._remove_monitor()
        self.assertEqual(page_monitor.load_monitors(self.base), [])
        self.assertFalse(self.page.btn_monitor_remove.isEnabled())
        self.assertIn("Nothing watched yet", self.page.monitors_list.item(0).text())

    def test_lock_now_re_locks_the_session(self):
        security.set_passcode(self.base, "1234")
        security._UNLOCKED.add(self.base)
        self.page.refresh()
        self.assertTrue(self.page.btn_lock_now.isEnabled())
        with mock.patch.object(pages_module.QMessageBox, "information"):
            self.page._lock_now()
        self.assertFalse(security.is_unlocked(self.base))
        self.assertFalse(self.page.btn_lock_now.isEnabled())

    def test_google_sign_out_clears_the_account(self):
        prefs.set_google_account(self.base, {"email": "mei@example.com"})
        prefs.set_google_token_cache(self.base, {"access_token": "a", "expires_in": 3600})
        self.page.refresh()
        self.assertIn("mei@example.com", self.page.lbl_google_status.text())
        # Sign-out lives in the card's overflow menu now, so its enabled state is
        # the action's — a button nobody added to a layout is not a UI.
        self.assertIsNotNone(self.page.google_sign_out_action)
        self.assertTrue(self.page.google_sign_out_action.isEnabled())
        self.page._google_sign_out()
        self.assertFalse(prefs.get_google_account(self.base))
        self.assertIn("Not signed in", self.page.lbl_google_status.text())
        self.assertFalse(self.page.google_sign_out_action.isEnabled())

    def test_verify_token_reuses_the_cache_and_persists_the_refresh(self):
        prefs.set_google_oauth_client_id(self.base, "cid.apps.googleusercontent.com")
        prefs.set_google_token_cache(self.base, {"access_token": "fresh", "expires_in": 3600})
        with mock.patch.object(
            pages_module.google_auth, "ensure_valid_token", return_value={"access_token": "refreshed"}
        ) as ensure:
            self.page._google_verify()
        ensure.assert_called_once()
        self.assertEqual(prefs.get_google_token_cache(self.base)["access_token"], "refreshed")
        self.assertIn("Token is valid", self.page.lbl_google_status.text())

    def test_sign_in_stores_the_account_and_the_device_token(self):
        prefs.set_google_oauth_client_id(self.base, "cid.apps.googleusercontent.com")
        payload = {
            "account": {"email": "mei@example.com", "name": "Mei"},
            "tokens": {"access_token": "t", "refresh_token": "r", "expires_in": 3600},
        }
        with mock.patch.object(pages_module.google_auth, "sign_in_via_device_code", return_value=payload) as sign_in:
            self.page._google_sign_in()
        sign_in.assert_called_once_with("cid.apps.googleusercontent.com")
        self.assertEqual(prefs.get_google_account(self.base)["email"], "mei@example.com")
        self.assertEqual(prefs.get_google_token_cache(self.base)["refresh_token"], "r")
        self.assertTrue(self.page.btn_google_sign_in.isEnabled())

    def test_the_settings_card_writes_a_bundle_where_the_user_asked(self):
        target = os.path.join(self.base, "diag.zip")
        with mock.patch.object(
            pages_module.QFileDialog, "getSaveFileName", return_value=(target, "Zip archive (*.zip)")
        ), mock.patch.object(pages_module.QMessageBox, "information") as told:
            self.page._export_diagnostics()
        self.assertTrue(os.path.isfile(target))
        with zipfile.ZipFile(target) as bundle:
            self.assertIn("versions.json", bundle.namelist())
        self.assertIn("no note text", told.call_args[0][2])

    def test_cancelling_the_save_dialog_writes_nothing(self):
        with mock.patch.object(
            pages_module.QFileDialog, "getSaveFileName", return_value=("", "")
        ), mock.patch.object(pages_module.QMessageBox, "information") as told:
            self.page._export_diagnostics()
        told.assert_not_called()

    def test_the_log_folder_button_points_at_the_log_dir(self):
        with mock.patch.object(pages_module.QDesktopServices, "openUrl") as opened:
            self.page._open_log_folder()
        self.assertTrue(opened.called)
        self.assertTrue(self.page._log_dir().endswith("logs"))

    def test_every_settings_button_is_on_the_page(self):
        # The rewire that folded the Google card's verbs into one menu first left
        # "Sign out" and "Set client ID…" behind as orphan buttons: created,
        # connected, greyed out on refresh — and never shown to anyone.
        detached = [
            name
            for name, value in vars(self.page).items()
            if name.startswith("btn_") and isinstance(value, QWidget) and not self.page.isAncestorOf(value)
        ]
        self.assertEqual(detached, [], "a settings button that no layout ever shows")

    def test_the_google_menu_owns_setup_and_sign_out(self):
        labels = [action.text() for action in self.page.btn_google_more.menu().actions()]
        self.assertIn("Set the client ID…", labels)
        self.assertIn("Sign out of Google", labels)

    def test_a_denied_sign_in_says_so(self):
        prefs.set_google_oauth_client_id(self.base, "cid.apps.googleusercontent.com")
        with mock.patch.object(pages_module.google_auth, "sign_in_via_device_code", return_value=None):
            self.page._google_sign_in()
        self.assertIn("denied", self.page.lbl_google_status.text())


class _DialogParent(QWidget):
    """The slice of PersonalWindow (and the browser window) these dialogs touch."""

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.refreshed = []
        self.flashed = []

    def _dialog_stylesheet(self):
        return ""

    def _refresh_plan(self):
        self.refreshed.append("plan")

    def _flash(self, message):
        self.flashed.append(message)

    def _refresh_workspace_combo(self):
        self.refreshed.append("workspace")

    def _apply_workspace_filter(self):
        self.refreshed.append("filter")

    def restore_tab_set(self, set_id):
        self.restored = set_id

    @staticmethod
    def _select_first_row(dialog) -> None:
        """A rename needs a selected row, exactly like a click needs one."""
        lists = dialog.findChildren(QListWidget)
        if lists and lists[0].count():
            lists[0].setCurrentRow(0)


class TestDialogPromotions(_ProfileCase):
    def test_workspace_rename_reaches_the_store(self):
        workspace_manager.ensure_dual_workspaces(self.base)
        parent = _DialogParent(self.base)

        def _rename_then_close(dialog):
            parent._select_first_row(dialog)
            click_dialog_verb(dialog, "Rename the selected workspace…")
            return 0

        with mock.patch.object(nav_module.QDialog, "exec_", _rename_then_close), mock.patch.object(
            nav_module.QInputDialog, "getText", return_value=("Study desk", True)
        ):
            nav_module.show_workspace_dialog(parent)
        names = [w["name"] for w in workspace_manager.get_workspaces_list(self.base)]
        self.assertIn("Study desk", names)
        self.assertIn("workspace", parent.refreshed)
        parent.deleteLater()

    def test_tab_set_rename_reaches_the_store(self):
        tab_set = tab_sets.add_tab_set(
            self.base, "search", "Old name", [{"title": "A", "url": "https://a.example"}]
        )
        parent = _DialogParent(self.base)

        def _rename_then_close(dialog):
            parent._select_first_row(dialog)
            click_dialog_verb(dialog, "Rename…")
            return 0

        with mock.patch.object(sessions_module.QDialog, "exec_", _rename_then_close), mock.patch.object(
            sessions_module.QInputDialog, "getText", return_value=("Research", True)
        ):
            sessions_module.show_tab_sets_dialog(parent)
        self.assertEqual(tab_sets.get_tab_set(self.base, tab_set["id"])["title"], "Research")
        parent.deleteLater()

    def test_semester_dialog_writes_the_plan_settings(self):
        parent = _DialogParent(self.base)

        def _fill_then_accept(dialog):
            dialog.findChildren(QLineEdit)[0].setText("HK1 2026-2027")
            return pw_module.QDialog.Accepted

        with mock.patch.object(pw_module.QDialog, "exec_", _fill_then_accept), mock.patch.object(
            pw_module, "QMessageBox"
        ):
            pw_module.PersonalWindow._edit_plan_settings(parent)
        semester = personal_plan.load_plan(self.base)["semester"]
        self.assertEqual(semester["name"], "HK1 2026-2027")
        self.assertTrue(semester["start_date"])
        self.assertTrue(semester["end_date"])
        parent.deleteLater()

    def test_semester_dialog_refuses_an_empty_name(self):
        parent = _DialogParent(self.base)
        with mock.patch.object(pw_module.QDialog, "exec_", lambda dialog: pw_module.QDialog.Accepted), mock.patch.object(
            pw_module.QMessageBox, "warning"
        ) as warning:
            pw_module.PersonalWindow._edit_plan_settings(parent)
        warning.assert_called_once()
        self.assertEqual(personal_plan.load_plan(self.base)["semester"]["name"], "")
        parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
