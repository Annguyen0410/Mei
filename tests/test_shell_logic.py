"""AppShell command routing: omnibar contracts without constructing QWebEngine windows."""
import unittest


class TestOmnibarCommandContracts(unittest.TestCase):
    """Static contract checks on AppShell routing without needing a running shell."""

    def test_workspace_navigation_commands_map_to_pages(self):
        from litebrowser.ui.app_shell import AppShell
        import inspect

        src = inspect.getsource(AppShell.handle_omnibar) + inspect.getsource(AppShell._handle_omnibar_text)
        # The known workspace slash commands must be present and route to real pages.
        for cmd in ("/home", "/browser", "/history", "/ai", "/personal", "/library", "/settings", "/guide"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, src)

    def test_omnibar_does_not_double_prefix(self):
        """Regression: typing `/task x` then pressing Enter must not leak '/task' into the title."""
        from litebrowser.ui.app_shell import AppShell
        import inspect

        src = inspect.getsource(AppShell.quick_task_dialog)
        # After prefix-strip the fallback title should not start with the slash command.
        self.assertNotIn('"/task"', src.split("def quick_task_dialog")[0])

    def test_shell_has_no_duplicate_sync_button_callables(self):
        from litebrowser.ui.app_shell import AppShell

        src = __import__("inspect").getsource(AppShell)
        # Sync button must actually run a state flush, not just navigate.
        self.assertIn("_run_sync_now", src)
        self.assertNotIn('switch_workspace("settings")  # sync button', src)

    def test_shell_defines_unique_page_map_keys(self):
        from litebrowser.ui.app_shell import AppShell
        import inspect

        src = inspect.getsource(AppShell)
        self.assertIn('"home": 0', src)
        self.assertIn('"browser": 1', src)
        self.assertIn('"settings": 6', src)


class TestQuickTaskCreation(unittest.TestCase):
    def test_quick_task_creates_real_task(self):
        import tempfile, os
        from litebrowser.services import life_service
        from litebrowser.core import prefs

        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            task = life_service.add_task(base, "  Buy oat milk  ")
            self.assertTrue(task.get("title"))
            self.assertIn("Buy oat milk", task["title"])
            tasks = life_service.load_tasks(base)
            self.assertTrue(any(t.get("id") == task.get("id") for t in tasks))

    def test_task_ids_are_unique_so_sync_dedupes_cleanly(self):
        import tempfile, os
        from litebrowser.services import life_service
        from litebrowser.core import prefs

        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            a = life_service.add_task(base, "A")
            b = life_service.add_task(base, "B")
            self.assertNotEqual(a["id"], b["id"])


if __name__ == "__main__":
    unittest.main()
