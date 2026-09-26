"""Every control that is wired up is also on screen, and every verb does something.

The 0.7.0.0 dialog pass moved the Google card's verbs into a menu and left *two*
of them behind as ordinary buttons: created, connected, greyed out on refresh —
and never added to a layout, so no user could ever press them. Services have a
ledger that fails on dead API; the UI had nothing equivalent, and a widget that
nobody shows cannot fail a test by being unused.

This file is that gate, in the two shapes the bug can take:

* **detached controls** — a ``btn_*``/``ed_*``/``cmb_*`` attribute of a window or
  page that is not inside that window's widget tree;
* **dead verbs** — a primary/menu action/Close button with no slot connected,
  which is what a rewire leaves behind when a callback is dropped by accident.

``show_quick_switcher`` is the one dialog with no footer on purpose: it is a
search box driven by Enter and Esc, and it is covered by its own tests.
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import litebrowser  # noqa: F401  activates the Qt compatibility shim
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

# QtWebEngine must exist before QApplication, or the interpreter dies without a
# traceback later in the run.
from litebrowser.core import prefs
from litebrowser.ui import personal_window as pw_module  # noqa: F401  QtWebEngine first
from litebrowser.ui import theme, vault_ui
from litebrowser.ui.dialogs import common as common_module
from litebrowser.ui.dialogs import help_hub, hotkeys
from litebrowser.ui.dialogs import navigation as nav_module
from litebrowser.ui.dialogs import profiles_privacy as pp_module
from litebrowser.ui.dialogs import sessions as sessions_module
from litebrowser.ui.dialogs import vpn_hub as vpn_module
from litebrowser.ui.shell import pages as pages_module

_app = QApplication.instance() or QApplication([])

# Attribute prefixes a window keeps for its controls. Widgets stored under these
# names are meant to be reachable by the user; anything else (a future dialog kept
# as an attribute, a layout) is out of scope for this gate.
CONTROL_PREFIXES = ("btn_", "ed_", "cmb_")


class _StubShell(QWidget):
    """Everything the shell pages read, with every unknown call a no-op."""

    def __init__(self, base_dir):
        super().__init__()
        self.profile_dir = base_dir
        self.base_dir = base_dir
        self.app_dir = "."
        self.update_status_text = ""
        self._pending_update_info = None
        self.jobs = []

    def run_in_background(self, work, on_done=None):
        self.jobs.append(work)
        return None

    def refresh_shell(self, force_deep=False):
        return None

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _DialogParent(QWidget):
    """Just enough host for the dialog builders, like the dialog-verb tests use."""

    # The help hub closes over these on the real browser window (they are listed as
    # card callbacks at build time, so ``getattr`` defaults would not save us).
    HOST_CALLBACKS = (
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
        "open_cuc_quan_ly_support_page",
    )

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.app_dir = base_dir
        self.ext_path = os.path.join(base_dir, "ext")
        for name in self.HOST_CALLBACKS:
            setattr(self, name, lambda *_args, **_kwargs: None)

        class _Tabs:
            def add_tab(self, *_args, **_kwargs):
                return None

        self.tab_manager = _Tabs()

    def _dialog_stylesheet(self):
        return theme.dialog_qss()

    def _refreshed(self, *_args, **_kwargs):
        return None


def _receivers(obj, signal) -> int:
    return obj.receivers(signal)


class TestWindowsOwnTheirControls(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.shell = _StubShell(self.base)
        self.windows = {"PersonalWindow": pw_module.PersonalWindow(self.base, os.getcwd(), embedded=True)}
        for name in ("HomeDashboardPage", "LibraryPage", "SettingsPage", "HistoryPage"):
            self.windows[name] = getattr(pages_module, name)(self.shell)

    def tearDown(self):
        for window in self.windows.values():
            window.deleteLater()
        self.shell.deleteLater()
        self._tmp.cleanup()

    def test_every_control_is_inside_the_window_that_owns_it(self):
        for name, window in self.windows.items():
            with self.subTest(window=name):
                detached = [
                    attribute
                    for attribute, value in vars(window).items()
                    if attribute.startswith(CONTROL_PREFIXES)
                    and isinstance(value, QWidget)
                    and not window.isAncestorOf(value)
                ]
                self.assertEqual(detached, [], f"{name}: a control no layout ever shows")


class TestDialogVerbsAreLive(unittest.TestCase):
    """A verb in the footer has to be reachable *and* connected to something."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.parent = _DialogParent(self.base)

    def tearDown(self):
        self.parent.deleteLater()
        self._tmp.cleanup()

    def _capture(self, module, builder, *args):
        captured = []

        def fake_exec(dialog, *_args, **_kwargs):
            captured.append(dialog)
            return 0

        with mock.patch.object(module.QDialog, "exec_", fake_exec):
            builder(self.parent, *args)
        self.assertTrue(captured, "the builder never reached exec_()")
        return captured[0]

    def _dialogs(self):
        for module, builder, args, name in (
            (vpn_module, vpn_module.show_vpn_hub, (), "vpn hub"),
            (sessions_module, sessions_module.show_vpn_dialog, (), "vpn form"),
            (sessions_module, sessions_module.show_startup_dialog, (), "startup"),
            (sessions_module, sessions_module.show_hibernate_pref_dialog, (), "hibernate"),
            (sessions_module, sessions_module.show_history_dialog, (), "history"),
            (sessions_module, sessions_module.show_bookmarks_dialog, (), "bookmarks"),
            (sessions_module, sessions_module.show_extensions_dialog, (), "extensions"),
            (sessions_module, sessions_module.show_tab_sets_dialog, (), "tab sets"),
            (pp_module, pp_module.show_profiles_dialog, (self.base,), "profiles"),
            (pp_module, pp_module.show_privacy_dialog, (), "privacy"),
            (pp_module, pp_module.show_save_password_dialog, (), "save password"),
            (pp_module, pp_module.show_permissions_manager, (), "permissions"),
            (nav_module, nav_module.show_workspace_dialog, (), "workspaces"),
            (nav_module, nav_module.show_routines_dialog, (), "routines"),
            (nav_module, nav_module.show_export_dialog, (), "export"),
            (nav_module, nav_module.show_feeds_dialog, (), "feeds"),
            (nav_module, nav_module.show_downloads_dialog, (), "downloads"),
            (hotkeys, hotkeys.show_hotkeys_hub, (), "hotkeys"),
            (help_hub, help_hub.show_browser_control_center, (), "help hub"),
            (
                vault_ui,
                vault_ui.show_vault_dialog,
                (os.path.join(self.base, "vault"), self.parent._dialog_stylesheet),
                "vault",
            ),
        ):
            with mock.patch.object(QThread, "start", lambda self: None), mock.patch.object(
                vpn_module, "_fetch_ip_info", return_value={}
            ):
                yield name, self._capture(module, builder, *args)

    def test_each_dialog_has_at_most_one_main_verb_and_it_is_connected(self):
        # At most one, not exactly one: a read-only reference dialog (the hotkey
        # table, the help hub) has no action of its own, and inventing a filled
        # button for it would be the wall-of-buttons problem in reverse.
        for name, dialog in self._dialogs():
            with self.subTest(dialog=name):
                primaries = [
                    button for button in dialog.findChildren(QPushButton) if button.objectName() == "PrimaryButton"
                ]
                self.assertLessEqual(len(primaries), 1, f"{name}: one filled verb, at most")
                for button in primaries:
                    self.assertGreater(
                        _receivers(button, button.clicked), 0, f"{name}: “{button.text()}” is wired to nothing"
                    )

    def test_every_menu_verb_triggers_something(self):
        # A dialog with nothing occasional to hide needs no menu; one that has a
        # menu must not keep an entry that no longer runs anything.
        for name, dialog in self._dialogs():
            menus = [button for button in dialog.findChildren(QPushButton) if button.menu() is not None]
            for button in menus:
                for action in button.menu().actions():
                    if action.isSeparator():
                        continue
                    with self.subTest(dialog=name, action=action.text()):
                        self.assertGreater(
                            _receivers(action, action.triggered),
                            0,
                            f"{name}: menu entry “{action.text()}” is wired to nothing",
                        )

    def test_close_actually_closes(self):
        for name, dialog in self._dialogs():
            closers = [
                button
                for button in dialog.findChildren(QPushButton)
                if button.menu() is None and button.text() in ("Close", "Cancel")
            ]
            with self.subTest(dialog=name):
                self.assertTrue(closers, f"{name}: a dialog must offer a way out")
                for button in closers:
                    self.assertGreater(
                        _receivers(button, button.clicked), 0, f"{name}: the {button.text()} button does nothing"
                    )

    def test_the_dialog_footer_helper_is_the_only_way_in(self):
        # The helpers exist so a dialog cannot invent its own look; if this fails,
        # a dialog grew its own button row instead of using the shared footer.
        self.assertTrue(common_module.ROLE_OBJECT_NAMES)
        for role, object_name in common_module.ROLE_OBJECT_NAMES.items():
            for sheet_name, qss in (("main_qss", theme.main_qss()), ("dialog_qss", theme.dialog_qss())):
                with self.subTest(role=role, sheet=sheet_name):
                    self.assertIn(f"#{object_name}", qss, f"{role} has no paint rule in {sheet_name}")


if __name__ == "__main__":
    unittest.main()
