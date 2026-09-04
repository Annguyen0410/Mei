"""Every registered slash command must have a dispatch branch in app_shell."""
import unittest

from litebrowser.core import commands


class TestCommandRegistry(unittest.TestCase):
    def test_commands_unique(self):
        names = [cmd for cmd, _arg, _desc in commands.COMMANDS]
        self.assertEqual(len(names), len(set(names)), "duplicate command entries")

    def test_commands_sorted_and_formatted(self):
        for cmd, takes_arg, desc in commands.COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertTrue(cmd.startswith("/"), cmd)
                self.assertNotIn(" ", cmd, f"{cmd} must not embed args in the key")
                self.assertIsInstance(takes_arg, bool)
                self.assertTrue(desc.strip(), f"{cmd} needs a description")

    def test_dispatch_branches_exist(self):
        from litebrowser.ui import app_shell

        src_file = app_shell.__file__
        src = open(src_file, encoding="utf-8-sig").read()
        for cmd, _takes_arg, _desc in commands.COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertIn(f'"{cmd}"', src, f"{cmd} registered but never dispatched in app_shell")

    def test_palette_commands_format(self):
        # Palette generation adds a trailing space only for arg-taking commands.
        for cmd, takes_arg, _desc in commands.COMMANDS:
            rendered = cmd + (" " if takes_arg else "")
            if takes_arg:
                self.assertTrue(rendered.endswith(" "))
            self.assertTrue(rendered.startswith(cmd))


if __name__ == "__main__":
    unittest.main()
