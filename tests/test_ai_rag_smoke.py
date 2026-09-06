"""AI/RAG smoke: index + search returns something sensible from notes/pages/tasks."""
import base64
import inspect
import json
import os
import tempfile
import unittest
from unittest import mock

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

    def test_vision_rejects_invalid_and_oversized_images(self):
        self.assertIsNone(ai_service.call_ollama_vision("llava", "Describe", "not-base64"))
        oversized = base64.b64encode(b"x" * (ai_service._MAX_VISION_IMAGE_BYTES + 1)).decode("ascii")
        self.assertIsNone(ai_service.call_ollama_vision("llava", "Describe", oversized))

    def test_vision_uses_fixed_loopback_endpoint_and_ollama_payload(self):
        seen = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"message":{"content":"The page shows a study planner."}}'

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["payload"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        image = base64.b64encode(b"png-bytes").decode("ascii")
        with mock.patch.object(ai_service.urllib.request, "urlopen", side_effect=fake_urlopen):
            answer = ai_service.call_ollama_vision("llava:latest", "What is visible?", image)

        self.assertEqual(answer, "The page shows a study planner.")
        self.assertEqual(seen["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(seen["timeout"], 60)
        self.assertEqual(seen["payload"]["model"], "llava:latest")
        self.assertEqual(seen["payload"]["messages"][0]["images"], [image])
        self.assertFalse(seen["payload"]["stream"])

    def test_clear_thread_clears_one_shot_external_context(self):
        from litebrowser.ui.ai_window import AIWindow

        source = inspect.getsource(AIWindow._clear_thread)
        self.assertIn('self._external_context = ""', source)
        self.assertIn('self._external_context_label = "Workspace-wide"', source)

    def test_provider_switch_discards_pending_screenshot(self):
        from litebrowser.ui.ai_window import AIWindow

        source = inspect.getsource(AIWindow._on_provider_change)
        self.assertIn('self._pending_screenshot_b64 = ""', source)
        self.assertIn('provider != "ollama"', source)

    def test_answer_query_only_routes_screenshot_to_local_ollama(self):
        with mock.patch.object(ai_service, "build_context", return_value=("context", [])), mock.patch.object(
            ai_service, "call_ollama_vision", return_value="vision answer"
        ) as vision:
            result = ai_service.answer_query(
                self.base,
                "What is visible?",
                provider="ollama",
                model="llava",
                screenshot_b64=base64.b64encode(b"image").decode("ascii"),
            )
        self.assertEqual(result["answer"], "vision answer")
        self.assertTrue(result["vision_used"])
        vision.assert_called_once()

        with mock.patch.object(ai_service, "build_context", return_value=("context", [])), mock.patch.object(
            ai_service, "call_ollama_vision", return_value="should not run"
        ) as vision:
            result = ai_service.answer_query(
                self.base,
                "What is visible?",
                provider="openrouter",
                screenshot_b64=base64.b64encode(b"image").decode("ascii"),
            )
        self.assertFalse(result["vision_used"])
        vision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
