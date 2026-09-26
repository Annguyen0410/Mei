"""Planner + flashcards reach every cross-cutting surface.

The study data lives in its own stores; these tests pin the wiring that makes
the AI index, library search, the morning brief and the library filters see it
exactly like the legacy life_service collections.
"""
import os
import tempfile
import time
import unittest

from litebrowser.core import prefs
from litebrowser.services import (
    ai_service,
    brief_service,
    flashcard_service,
    life_service,
    personal_plan,
)
from litebrowser.ui.shell.pages import LibraryPage


class TestPlannerSurfaces(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.course = personal_plan.create_course(self.base, "Giải tích", code="MA101")
        self.item = personal_plan.create_item(
            self.base,
            "Ôn chương 3",
            kind="assignment",
            course_id=self.course["id"],
            due_date="2026-10-01",
            tags=["derivative"],
        )
        self.block = personal_plan.create_time_block(
            self.base, "Deep study", "2026-10-01", 540, course_id=self.course["id"]
        )
        self.card = flashcard_service.add_card(self.base, "Đạo hàm của sin?", "cos")

    def tearDown(self):
        self._tmp.cleanup()

    def test_ai_index_contains_planner_items_and_cards(self):
        by_source = {}
        for doc in ai_service.collect_docs(self.base):
            by_source.setdefault(doc.source, []).append(doc)

        self.assertIn("planner_item", by_source)
        self.assertIn("planner_course", by_source)
        self.assertIn("planner_block", by_source)
        self.assertIn("flashcard", by_source)
        item_doc = by_source["planner_item"][0]
        self.assertEqual(item_doc.meta["plan_item_id"], self.item["id"])
        self.assertIn("Giải tích", item_doc.snippet)
        self.assertIn("2026-10-01", item_doc.snippet)
        self.assertEqual(by_source["flashcard"][0].meta["card_id"], self.card["id"])

    def test_search_everything_finds_planner_and_cards(self):
        kinds = {entry["kind"] for entry in life_service.search_everything(self.base, "chương")}
        self.assertIn("planner-item", kinds)
        self.assertIn(
            "flashcard",
            {entry["kind"] for entry in life_service.search_everything(self.base, "sin")},
        )
        self.assertIn(
            "planner-course",
            {entry["kind"] for entry in life_service.search_everything(self.base, "giải tích")},
        )
        self.assertIn(
            "planner-block",
            {entry["kind"] for entry in life_service.search_everything(self.base, "deep study")},
        )

    def test_brief_surfaces_study_deadlines_and_blocks(self):
        personal_plan.update_item(
            self.base, self.item["id"], due_date="2020-01-01", scheduled_date="2020-01-01"
        )
        personal_plan.update_time_block(
            self.base, self.block["id"], date=time.strftime("%Y-%m-%d")
        )

        brief = brief_service.build_morning_brief(self.base)
        self.assertIn("Ôn chương 3 (Giải tích)", brief["planner_overdue"])
        self.assertEqual([b["title"] for b in brief["planner_blocks_today"]], ["Deep study"])
        self.assertEqual(brief["flashcards_due"], 1)

        markdown = brief_service.brief_markdown(brief)
        self.assertIn("Study — overdue", markdown)
        self.assertIn("Time blocks today", markdown)
        self.assertIn("flashcards due", markdown)
        self.assertIn("study deadline", brief_service.brief_text(brief))

    def test_library_filters_know_the_new_kinds(self):
        self.assertTrue(LibraryPage._matches_library_filter({"kind": "planner-item"}, "planner"))
        self.assertTrue(LibraryPage._matches_library_filter({"kind": "planner-block"}, "planner"))
        self.assertTrue(LibraryPage._matches_library_filter({"kind": "planner-course"}, "planner"))
        self.assertTrue(LibraryPage._matches_library_filter({"kind": "flashcard"}, "cards"))
        self.assertFalse(LibraryPage._matches_library_filter({"kind": "task"}, "cards"))


if __name__ == "__main__":
    unittest.main()
