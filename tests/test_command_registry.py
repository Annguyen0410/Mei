"""One registry drives autocomplete, hints, palette and docs.

The old contract here only asserted that a command's literal appeared somewhere in
``app_shell.py``, which is why the hand-written autocomplete list could sit six
commands behind the registry without any test noticing.
"""
import inspect
import os
import re
import unittest

from litebrowser.core import commands


class TestRegistryShape(unittest.TestCase):
    def test_names_unique(self):
        names = list(commands.command_names())
        self.assertEqual(len(names), len(set(names)), "duplicate command entries")

    def test_entries_well_formed(self):
        for cmd in commands.COMMANDS:
            with self.subTest(cmd=cmd.name):
                self.assertTrue(cmd.name.startswith("/"), cmd.name)
                self.assertNotIn(" ", cmd.name, f"{cmd.name} must not embed args in the key")
                self.assertIsInstance(cmd.takes_arg, bool)
                self.assertTrue(cmd.description.strip(), f"{cmd.name} needs a description")
                self.assertIn(cmd.kind, ("action", "nav"), cmd.kind)

    def test_both_kinds_are_present(self):
        self.assertTrue(commands.action_names())
        self.assertTrue(commands.nav_names())

    def test_completion_only_pads_argument_commands(self):
        for cmd in commands.COMMANDS:
            with self.subTest(cmd=cmd.name):
                expected = cmd.name + (" " if cmd.takes_arg else "")
                self.assertEqual(cmd.completion(), expected)

    def test_hint_includes_example_when_present(self):
        hint = commands.by_name("/template").hint()
        self.assertIn("Daily plan", hint)
        self.assertIn("/template daily", hint)
        self.assertEqual(commands.by_name("/status").hint(), commands.by_name("/status").description)

    def test_by_name_is_exact(self):
        self.assertIsNone(commands.by_name("status"))
        self.assertIsNone(commands.by_name("/nope"))
        self.assertEqual(commands.by_name("/status").name, "/status")


class TestSurfacesAreGenerated(unittest.TestCase):
    """No surface may keep its own copy of the command list."""

    def _source(self, module):
        return inspect.getsource(module)

    def test_omnibar_completer_is_generated(self):
        from litebrowser.ui import app_shell

        src = self._source(app_shell)
        self.assertNotIn("QCompleter([", src, "hand-written autocomplete list is back")
        self.assertIn("_command_completions()", src)

    def test_completer_covers_every_registered_command(self):
        completions = commands.completions()
        self.assertEqual(len(completions), len(commands.COMMANDS))
        # The length assertion above is what makes strict pairing correct here.
        for cmd, completion in zip(commands.COMMANDS, completions, strict=True):
            with self.subTest(cmd=cmd.name):
                self.assertEqual(completion.strip(), cmd.name)

    def test_late_added_commands_are_offered(self):
        # These six were registered but missing from the autocomplete.
        offered = {c.strip() for c in commands.completions()}
        for name in ("/accent", "/export", "/review", "/routines", "/template", "/theme"):
            with self.subTest(cmd=name):
                self.assertIn(name, offered)

    def test_hints_cover_every_command(self):
        self.assertEqual(set(commands.hints()), set(commands.command_names()))

    def test_palette_reads_registry_fields(self):
        from litebrowser.ui.dialogs import shell_palette

        src = self._source(shell_palette)
        self.assertIn("command.completion()", src)
        self.assertNotIn("for cmd, takes_arg, desc in COMMANDS", src)

    def test_quick_switcher_reads_registry_fields(self):
        from litebrowser.ui.dialogs import navigation

        src = self._source(navigation)
        self.assertIn("cmd.completion()", src)
        self.assertNotIn('("/cql", "Cục Quản Lý")', src, "hand-maintained command list is back")


class TestDispatchBranchesExist(unittest.TestCase):
    def test_every_registered_command_is_dispatched(self):
        from litebrowser.ui import app_shell

        src = open(app_shell.__file__, encoding="utf-8-sig").read()
        for cmd in commands.COMMANDS:
            with self.subTest(cmd=cmd.name):
                self.assertIn(f'"{cmd.name}"', src, f"{cmd.name} registered but never dispatched in app_shell")


class TestDocsCoverEveryCommand(unittest.TestCase):
    def test_registry_is_documented(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "docs", "COMMAND_REFERENCE.md"), encoding="utf-8") as handle:
            doc = handle.read()
        documented = {"/" + name for name in re.findall(r"`\/([a-z0-9-]+)", doc)}
        missing = sorted(set(commands.command_names()) - documented)
        self.assertEqual(missing, [], f"undocumented commands: {missing}")


if __name__ == "__main__":
    unittest.main()
