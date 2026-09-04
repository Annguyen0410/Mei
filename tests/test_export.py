"""Export center: HTML site is well-formed, MD bundle round-trips."""
import os
import tempfile
import unittest
import zipfile

from litebrowser.core import prefs
from litebrowser.services import export_service, personal_service


class TestExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        personal_service.create_note(self.base, "Alpha", "# Alpha\n\nbody one", category="General")
        personal_service.create_note(self.base, "Beta", "# Beta\n\n[[Alpha]] link", category="Work")

    def tearDown(self):
        self._tmp.cleanup()

    def test_md_zip_contains_notes(self):
        out = os.path.join(self._tmp.name, "notes-md.zip")
        count = export_service.export_notes_md_zip(self.base, out)
        self.assertEqual(count, 2)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            self.assertIn("index.md", names)
            self.assertTrue(any(n.endswith(".md") and "Alpha" in n for n in names))

    def test_html_site_is_wellformed(self):
        out = os.path.join(self._tmp.name, "notes-site.zip")
        count = export_service.export_notes_html(self.base, out)
        self.assertEqual(count, 2)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            self.assertIn("index.html", names)
            index = zf.read("index.html").decode("utf-8")
        # The list must be INSIDE the document, not appended after </html>.
        self.assertIn("Alpha", index)
        self.assertIn("Beta", index)
        self.assertTrue(index.rstrip().endswith("</html>"), "index must end with </html>")
        self.assertEqual(index.count("</html>"), 1)

    def test_empty_vault_exports_zero(self):
        empty = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "empty"))
        out = os.path.join(self._tmp.name, "e.zip")
        self.assertEqual(export_service.export_notes_html(empty, out), 0)
        self.assertEqual(export_service.export_notes_md_zip(empty, out), 0)


if __name__ == "__main__":
    unittest.main()
