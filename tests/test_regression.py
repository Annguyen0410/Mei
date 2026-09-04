"""Regression guards for the bugs fixed in rounds 1-3 of this maintenance pass."""
import inspect
import unittest


class TestCloseEventSafety(unittest.TestCase):
    """AppShell/SearchWindow close handlers must be idempotent and never recursively
    close child widgets searched by the window manager."""

    def test_app_shell_close_event_is_idempotent(self):
        from litebrowser.ui import app_shell
        src = inspect.getsource(app_shell.AppShell.closeEvent)
        self.assertIn("_closing", src)
        # It must NOT explicitly close children; Qt cascades close events to them.
        self.assertNotIn("self.browser_page.close()", src)
        self.assertNotIn("self.ai_page.close()", src)

    def test_search_window_close_event_is_idempotent(self):
        from litebrowser.ui.main_window import window
        src = inspect.getsource(window.SearchWindow.closeEvent)
        self.assertIn("_closing", src)

    def test_ai_window_answer_handler_populates_question_before_logging(self):
        from litebrowser.ui import ai_window
        src = inspect.getsource(ai_window.AIWindow._finish_assistant_query)
        # Regression: the undefined `question` crash in the AI pane.
        self.assertIn("self._last_question", src)


class TestWebEngineProfileIsolation(unittest.TestCase):
    def test_search_window_accepts_window_slot_kwarg(self):
        sig = inspect.signature(__import__("litebrowser.ui.main_window.window", fromlist=["SearchWindow"]).SearchWindow.__init__)
        self.assertIn("window_slot", sig.parameters)

    def test_profile_storage_path_uses_slot_subdirectory(self):
        from litebrowser.ui.main_window import window
        src = inspect.getsource(window.SearchWindow._configure_web_profile)
        self.assertIn("slot", src)
        self.assertIn("setPersistentStoragePath", src)


class TestDownloadFinalizationIsResilient(unittest.TestCase):
    def test_download_request_prefers_state_changed(self):
        from litebrowser.ui.main_window import window
        src = inspect.getsource(window.SearchWindow.handle_download_request)
        self.assertIn("stateChanged", src)


class TestDuplicatesRemoved(unittest.TestCase):
    def test_dead_guide_dialog_functions_removed(self):
        from litebrowser.ui.dialogs import navigation, help_hub
        self.assertFalse(hasattr(navigation, "show_guide"))
        self.assertFalse(hasattr(help_hub, "show_modern_guide"))

    def test_extension_import_appears_once_in_browser_menus(self):
        from litebrowser.ui.main_window import window, window_menus

        # The entry may live on SearchWindow or its menu mixins — count the
        # whole MRO's sources so duplicates across files are still caught.
        sources = [
            inspect.getsource(window.SearchWindow),
            inspect.getsource(window_menus.MenusMixin),
        ]
        count = sum(s.count('addAction("Extension Import Center")') for s in sources)
        self.assertEqual(count, 1, f"duplicate menu entries remain: {count}")


if __name__ == "__main__":
    unittest.main()
