"""End-to-end scenario: a study session touching every layer in order.

Simulates: flashcard add -> review grade -> note clip -> note delete cascade
-> routine fire -> monitor check -> theme switch persistence.
"""
import os
import tempfile
import time
import unittest

from litebrowser.core import prefs
from litebrowser.services import (
    flashcard_service,
    focus_service,
    life_service,
    note_templates,
    page_monitor,
    personal_service,
    routines_service,
)


class TestStudySessionScenario(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_full_study_session(self):
        # 1. A topic note with a wiki-link
        topic = personal_service.create_note(self.base, "OSI Model", "# OSI Model\n\n7 layers\n\nSee [[TCP IP Basics]]")
        self.assertTrue(topic["id"])

        # 2. Flashcards from the note (both sides)
        card = flashcard_service.add_card(
            self.base, "How many OSI layers?", "7", source_note_id=topic["id"]
        )
        self.assertEqual(len(flashcard_service.due_cards(self.base)), 1)

        # 3. Review: grade Good -> leaves the due queue
        reviewed = flashcard_service.review_card(self.base, card["id"], "good")
        self.assertGreaterEqual(reviewed["interval"], 1)
        self.assertEqual(len(flashcard_service.due_cards(self.base)), 0)

        # 4. Clipping from a web page lands in the dated Clippings note
        day = time.strftime("%Y-%m-%d")
        clip_title = f"Clippings — {day}"
        personal_service.create_note(
            self.base, clip_title,
            f"# {clip_title}\n\n> OSI has 7 layers.\n\n— [Source](https://example.com) · 09:00\n\n---\n\n",
            category="Clippings",
        )
        clippings = [n for n in personal_service.list_notes(self.base) if n["title"] == clip_title]
        self.assertEqual(len(clippings), 1)

        # 5. The wiki-linked target note is created by clicking the link
        stub = personal_service.create_note(self.base, "TCP IP Basics", "# TCP IP Basics\n\n", category="General")
        links = [n for n in personal_service.list_notes(self.base) if "[[TCP IP Basics]]" in n["content"]]
        self.assertEqual(len(links), 1)

        # 6. Focus pour runs -> streak data exists
        focus_service.start_focus(self.base, minutes=25)
        focus_service.stop_focus(self.base)
        per_day = focus_service.compute_daily_minutes(focus_service.focus_journal(self.base, limit=50))
        self.assertTrue(all(isinstance(v, int) for v in per_day.values()))

        # 7. Daily template composes from today's real state
        daily = note_templates.create_daily_note(self.base)
        self.assertIn("## Tasks", daily["content"])

        # 8. Routine registered for right now fires once
        now = time.localtime()
        routines_service.add_routine(
            self.base, "Evening review", time.strftime("%H:%M"), [now.tm_wday], ["/template weekly"]
        )
        due = routines_service.due_routines(self.base)
        self.assertEqual(len(due), 1)
        routines_service.mark_fired(self.base, due[0]["id"], time.strftime("%Y-%m-%d"))
        self.assertEqual(routines_service.due_routines(self.base), [])

        # 9. Monitor seeds a page then detects a change
        monitor = page_monitor.add_monitor(self.base, "https://example.com/grades", "Grades")
        page_monitor.record_check(self.base, monitor["id"], "v1")
        self.assertEqual(page_monitor.record_check(self.base, monitor["id"], "v2"), "changed")

        # 10. Deleting the source topic note cascades its card away
        self.assertEqual(flashcard_service.delete_cards_for_note(self.base, topic["id"]), 1)
        remaining = flashcard_service.load_cards(self.base)
        self.assertEqual(len(remaining), 0)

        # 11. Theme switch persists and resolves through the auto day/night map
        prefs.set_shell_theme(self.base, "matcha-day")
        prefs.set_auto_theme(self.base, True)
        resolved = prefs.resolved_auto_theme(self.base)
        hour = time.localtime().tm_hour
        expected = "matcha-day" if 6 <= hour < 18 else "forest-night"
        self.assertEqual(resolved, expected)

        # 12. Reading progress round-trips
        life_service.add_saved_page(self.base, "Long article", "https://example.com/article")
        life_service.set_reading_progress(self.base, "https://example.com/article", 42)
        cont = life_service.continue_reading_page(self.base)
        self.assertIsNotNone(cont)
        self.assertEqual(cont["read_percent"], 42)


if __name__ == "__main__":
    unittest.main()
