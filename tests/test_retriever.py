import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import ai_service, personal_service, retriever


class TestRetriever(unittest.TestCase):
    def test_unicode_chunked_note_is_ranked_and_auto_refreshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            personal_service.create_note(base, "Mật mã", ("Giới thiệu. " * 250) + "\n\nHelios là mật mã cần tìm.")
            docs = ai_service.index_docs(base)
            self.assertGreater(len([doc for doc in docs if doc.source == "vault_note"]), 1)
            found = retriever.search(base, "mat ma helios")
            self.assertTrue(found)
            self.assertIn("Helios", found[0][1].snippet)

            personal_service.create_note(base, "Second", "Lumen project details")
            refreshed = retriever.search(base, "lumen")
            self.assertTrue(refreshed)
            self.assertEqual(refreshed[0][1].title, "Second")

    def test_remote_endpoint_is_not_user_redirectable(self):
        self.assertIsNone(ai_service.call_openrouter("key", "model", "prompt", base_url="http://127.0.0.1:1"))


if __name__ == "__main__":
    unittest.main()
