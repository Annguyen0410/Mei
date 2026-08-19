"""Unicode-safe note paths (Vietnamese categories/titles)."""
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import personal_service


class TestPersonalUnicodeNames(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_note_vietnamese_category_and_title(self):
        note = personal_service.create_note(
            self.base,
            "Tiêu đề thử",
            "Nội dung",
            category="Ghi chú / Việt",
        )
        self.assertIsNotNone(note)
        self.assertIn("Ghi chú", note["id"].replace("\\", "/"))
        self.assertIn("Việt", note["id"].replace("\\", "/"))
        self.assertIn("Tiêu đề", note["id"])
        path = personal_service._note_path(self.base, note["id"])
        self.assertTrue(os.path.isfile(path))

    def test_safe_name_strips_windows_forbidden_only(self):
        self.assertEqual(personal_service._safe_name("  Hello:World  "), "Hello-World")
        self.assertIn("ử", personal_service._safe_name("Thử nghiệm"))

    def test_note_id_cannot_escape_vault(self):
        self.assertEqual(personal_service._note_path(self.base, "..\\outside.md"), "")
        self.assertIsNone(personal_service.read_note(self.base, "..\\outside.md"))


if __name__ == "__main__":
    unittest.main()
