"""Flashcards + SM-2 lite scheduler checks."""
import os
import tempfile
import time
import unittest

from litebrowser.core import prefs
from litebrowser.services import flashcard_service


class TestFlashcards(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_list(self):
        card = flashcard_service.add_card(self.base, "What is SM-2?", "A spaced repetition algorithm")
        self.assertEqual(len(flashcard_service.load_cards(self.base)), 1)
        self.assertEqual(card["ease"], 2.5)
        self.assertEqual(card["interval"], 0)

    def test_due_now_and_after_good(self):
        card = flashcard_service.add_card(self.base, "Q", "A")
        self.assertEqual(len(flashcard_service.due_cards(self.base)), 1)
        reviewed = flashcard_service.review_card(self.base, card["id"], "good")
        self.assertIsNotNone(reviewed)
        self.assertGreaterEqual(reviewed["interval"], 1)
        self.assertEqual(len(flashcard_service.due_cards(self.base)), 0)
        # Due again in ~interval days:
        future = int(time.time()) + int(reviewed["interval"] * 86400) + 60
        self.assertEqual(len(flashcard_service.due_cards(self.base, now=future)), 1)

    def test_again_resets_interval(self):
        card = flashcard_service.add_card(self.base, "Q", "A")
        flashcard_service.review_card(self.base, card["id"], "good")
        again = flashcard_service.review_card(self.base, card["id"], "again")
        self.assertEqual(again["interval"], 0)
        self.assertEqual(again["lapses"], 1)
        # Due almost immediately (10 min), not tomorrow:
        soon = int(time.time()) + 11 * 60
        self.assertEqual(len(flashcard_service.due_cards(self.base, now=soon)), 1)

    def test_ease_moves_and_clamps(self):
        card = flashcard_service.add_card(self.base, "Q", "A")
        easy = flashcard_service.review_card(self.base, card["id"], "easy")
        self.assertGreater(easy["ease"], 2.5)
        for _ in range(12):
            easy = flashcard_service.review_card(self.base, card["id"], "again")
        self.assertGreaterEqual(easy["ease"], flashcard_service._EASE_MIN)

    def test_invalid_grade_ignored(self):
        card = flashcard_service.add_card(self.base, "Q", "A")
        self.assertIsNone(flashcard_service.review_card(self.base, card["id"], "amazing"))

    def test_delete_card(self):
        card = flashcard_service.add_card(self.base, "Q", "A")
        self.assertTrue(flashcard_service.delete_card(self.base, card["id"]))
        self.assertEqual(flashcard_service.load_cards(self.base), [])


if __name__ == "__main__":
    unittest.main()
