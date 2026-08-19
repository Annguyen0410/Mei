"""AI/RAG smoke: index + search returns something sensible from notes/pages/tasks."""
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import ai_service, life_service, personal_service, retriever


class TestAIRAGSmoke(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_index_covers_notes_tasks_pages(self):
        personal_service.create_note(self.base, "Cafe Notes", "espresso beans and pourover notes")
        life_service.add_task(self.base, "Buy coffee filters", bucket="home")
        life_service.add_saved_page(self.base, "Coffee Blog", "https://coffee.example.org/brew")
        docs = ai_service.index_docs(self.base)
        self.assertTrue(any(d.source == "vault_note" for d in docs))
        self.assertTrue(any(d.source == "task" for d in docs))
        self.assertTrue(any(d.source == "saved_page" for d in docs))

    def test_retriever_returns_relevant_doc_for_query(self):
        personal_service.create_note(self.base, "Travel", "Hanoi itinerary, april flights, train tickets")
        result = retriever.search(self.base, "hanoi itinerary")
        self.assertTrue(result)
        # First hit should mention the note we just wrote.
        self.assertIn("Hanoi", result[0][1].snippet or "")


if __name__ == "__main__":
    unittest.main()
