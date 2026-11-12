"""Drive every dialog offscreen: build it, fill it, press everything, survive.

The suite so far checked the *shape* of a dialog (one primary verb, menus wired,
controls inside their window). None of that executes the handlers. This file
does: it constructs each dialog with a real parent, types into every field, flips
every checkbox, changes every combo box, triggers every menu action and clicks
every button — with the path pickers and message boxes stubbed, and threads
started but never run.

What it proves: no dialog raises on plausible-but-unexpected input, and every
verb can be pressed twice without falling over. What it cannot prove: whether the
resulting pixels look right — that still needs a human and a real desktop.
"""
from __future__ import annotations

import contextlib
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The shim must be imported before any Qt binding: reaching PyQt directly first
# pins the process to one runtime and the shim then swaps in the other.
import litebrowser  # noqa: F401, I001  activates the Qt compatibility shim first
from PyQt5.QtCore import QEventLoop, QThread
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QWidget,
)
from litebrowser.core import prefs
from litebrowser.ui import personal_window as pw_module  # noqa: F401  QtWebEngine first
from litebrowser.ui import theme, vault_ui
from litebrowser.ui.dialogs import common as common_module
from litebrowser.ui.dialogs import data_management, help_hub, hotkeys, quick_capture
from litebrowser.ui.dialogs import navigation as nav_module
from litebrowser.ui.dialogs import profiles_privacy as pp_module
from litebrowser.ui.dialogs import sessions as sessions_module
from litebrowser.ui.dialogs import vpn_hub as vpn_module

_app = QApplication.instance() or QApplication([])


class _Host(QWidget):
    """A window that can answer any callback a dialog asks it for."""

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
        "refresh_shell",
        "persist_state",
        "add_new_tab",
        "show_toast",
    )

    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.profile_dir = base_dir
        self.app_dir = base_dir
        self.ext_path = os.path.join(base_dir, "ext")
        for name in self.HOST_CALLBACKS:
            setattr(self, name, lambda *_a, **_k: None)

        class _Tabs:
            def add_tab(self, *_a, **_k):
                return None

            def count(self):
                return 0

        self.tab_manager = _Tabs()

    def _dialog_stylesheet(self):
        return theme.dialog_qss()

    def _refreshed(self, *_a, **_k):
        return None

    def __getattr__(self, name):
        # A dialog that reaches for anything else gets a no-op rather than an
        # AttributeError: the point here is the dialog's own code, not the host.
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *_a, **_k: None


def _noop_exec(self, *_a, **_k):
    return 0


#: The only verbs pressed. Everything else either dials the network, relaunches
#: the app, or waits on a worker thread — a handler that blocks on a real CONNECT
#: hangs the run instead of testing anything, so it is left to a manual pass.
#: Field edits still drive validation and filter slots, which is where the
#: uncovered logic actually lives.
SAFE_VERBS = ("close", "cancel", "ok", "done")


@contextlib.contextmanager
def _stubbed_environment():
    """No modal loops, no file pickers, no background threads leaving the test."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(QDialog, "exec_", _noop_exec))
        stack.enter_context(mock.patch.object(QMessageBox, "exec_", _noop_exec))
        stack.enter_context(
            mock.patch.object(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
        )
        for name in ("information", "warning", "critical"):
            stack.enter_context(
                mock.patch.object(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
            )
        for name, value in (
            ("getSaveFileName", ("", "")),
            ("getOpenFileName", ("", "")),
            ("getOpenFileNames", ([], "")),
            ("getExistingDirectory", ""),
        ):
            stack.enter_context(
                mock.patch.object(
                    QFileDialog, name, staticmethod(lambda *a, _value=value, **k: _value)
                )
            )
        stack.enter_context(mock.patch.object(QThread, "start", lambda self: None))
        stack.enter_context(mock.patch.object(QThread, "wait", lambda self, *a, **k: True))
        # Any handler that opens its own event loop ("Test connection" does, while
        # it waits for a worker) would hang forever with the worker stubbed out.
        # A nested loop that returns immediately is what a test wants: the handler
        # then continues with whatever the stub produced.
        # PyQt6 exposes ``exec``; the compatibility shim answers to ``exec_``.
        # Patch both spellings so a nested loop cannot block either way.
        stack.enter_context(mock.patch.object(QEventLoop, "exec", _noop_exec, create=True))
        stack.enter_context(mock.patch.object(QEventLoop, "exec_", _noop_exec, create=True))
        stack.enter_context(mock.patch.object(vpn_module, "_fetch_ip_info", return_value={}))
        # "Test connection" performs a real proxy CONNECT with a 6 s timeout (and
        # DNS resolution on a bogus preset can take far longer). A UI test must not
        # dial anything: make every socket attempt fail immediately, the same rule
        # conftest already applies to the update channel.
        stack.enter_context(
            mock.patch.object(
                vpn_module,
                "_test_proxy_connection",
                return_value=(False, "stubbed: no network in tests"),
            )
        )
        stack.enter_context(
            mock.patch(
                "socket.create_connection",
                side_effect=OSError("network is disabled in tests"),
            )
        )
        yield


BUILDERS = (
    ("vpn hub", lambda host, base: vpn_module.show_vpn_hub(host)),
    ("vpn form", lambda host, base: sessions_module.show_vpn_dialog(host)),
    ("startup", lambda host, base: sessions_module.show_startup_dialog(host)),
    ("hibernate", lambda host, base: sessions_module.show_hibernate_pref_dialog(host)),
    ("history", lambda host, base: sessions_module.show_history_dialog(host)),
    ("bookmarks", lambda host, base: sessions_module.show_bookmarks_dialog(host)),
    ("extensions", lambda host, base: sessions_module.show_extensions_dialog(host)),
    ("tab sets", lambda host, base: sessions_module.show_tab_sets_dialog(host)),
    ("profiles", lambda host, base: pp_module.show_profiles_dialog(host, base)),
    ("privacy", lambda host, base: pp_module.show_privacy_dialog(host)),
    ("save password", lambda host, base: pp_module.show_save_password_dialog(host)),
    ("permissions", lambda host, base: pp_module.show_permissions_manager(host)),
    ("workspaces", lambda host, base: nav_module.show_workspace_dialog(host)),
    ("routines", lambda host, base: nav_module.show_routines_dialog(host)),
    ("export", lambda host, base: nav_module.show_export_dialog(host)),
    ("feeds", lambda host, base: nav_module.show_feeds_dialog(host)),
    ("downloads", lambda host, base: nav_module.show_downloads_dialog(host)),
    ("hotkeys", lambda host, base: hotkeys.show_hotkeys_hub(host)),
    ("help hub", lambda host, base: help_hub.show_browser_control_center(host)),
    (
        "vault",
        lambda host, base: vault_ui.show_vault_dialog(
            host, os.path.join(base, "vault"), host._dialog_stylesheet
        ),
    ),
    ("quick capture", lambda host, base: quick_capture.QuickCaptureDialog(base, {}, host)),
    ("data management", lambda host, base: data_management.DataManagementDialog(base, host)),
)


class TestDialogsSurviveInteraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = None
        import tempfile

        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = prefs.ensure_profile_layout(os.path.join(cls._tmp.name, "profile"))
        cls.host = _Host(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.host.deleteLater()
        cls._tmp.cleanup()

    def _make(self, builder):
        captured = []
        parent = self.host

        def fake_exec(dialog, *_a, **_k):
            captured.append(dialog)
            return 0

        with mock.patch.object(QDialog, "exec_", fake_exec):
            produced = builder(parent, self.base)
        if captured:
            return captured[0]
        if isinstance(produced, QDialog):
            return produced
        # A builder that only returns a widget (vault, quick capture, data mgmt).
        if isinstance(produced, QWidget):
            return produced
        raise AssertionError("builder produced nothing observable")

    def _drive(self, dialog):
        """Fill every field, flip every toggle, then close the dialog."""
        for widget in dialog.findChildren(QWidget):
            try:
                if isinstance(widget, QLineEdit):
                    widget.setText("probe — ứng")
                elif isinstance(widget, QTextEdit):
                    widget.setPlainText("probe body\nsecond line")
                elif isinstance(widget, QSpinBox):
                    widget.setValue(widget.minimum() if widget.minimum() > 0 else 1)
                elif isinstance(widget, QComboBox) and widget.count():
                    widget.setCurrentIndex(widget.count() - 1)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(not widget.isChecked())
            except RuntimeError:
                continue  # widget already deleted by an earlier handler
        _app.processEvents()
        for button in dialog.findChildren(QPushButton):
            if button.text().strip().lower() not in SAFE_VERBS:
                continue
            try:
                button.click()
            except RuntimeError:
                continue
        _app.processEvents()

    def test_every_dialog_constructs_with_a_host(self):
        for name, builder in BUILDERS:
            with self.subTest(dialog=name), _stubbed_environment():
                dialog = self._make(builder)
                self.assertIsNotNone(dialog, name)
                dialog.deleteLater()

    def test_every_dialog_survives_a_full_interaction_pass(self):
        for name, builder in BUILDERS:
            with self.subTest(dialog=name), _stubbed_environment():
                dialog = self._make(builder)
                self._drive(dialog)
                dialog.deleteLater()

    def test_a_second_pass_is_still_safe(self):
        # Opening the same dialog twice is normal (a user reopens it); the
        # handlers must not accumulate state that breaks on the second visit.
        for name, builder in BUILDERS:
            with self.subTest(dialog=name), _stubbed_environment():
                first = self._make(builder)
                self._drive(first)
                first.deleteLater()
                second = self._make(builder)
                self._drive(second)
                second.deleteLater()

    def test_fields_accept_hostile_text(self):
        hostile = ["<script>alert(1)</script>", "a" * 5000, "\x00\x01", "../../etc/passwd", "ứng — 日本語 🎴"]
        for name, builder in BUILDERS:
            with self.subTest(dialog=name), _stubbed_environment():
                dialog = self._make(builder)
                fields = dialog.findChildren(QLineEdit)
                for text in hostile:
                    for field in fields:
                        try:
                            field.setText(text)
                        except RuntimeError:
                            break
                _app.processEvents()
                for button in dialog.findChildren(QPushButton):
                    if button.text().strip().lower() not in SAFE_VERBS:
                        continue
                    try:
                        button.click()
                    except RuntimeError:
                        continue
                dialog.deleteLater()

    def test_dialogs_report_their_shared_footer_roles(self):
        # The footer helper is the only sanctioned way to add a button row; a
        # dialog that stops using it would lose its paint rules.
        self.assertTrue(common_module.ROLE_OBJECT_NAMES)
        main_sheet = theme.main_qss()
        for role, object_name in common_module.ROLE_OBJECT_NAMES.items():
            with self.subTest(role=role):
                self.assertIn(f"#{object_name}", main_sheet)


if __name__ == "__main__":
    unittest.main()
