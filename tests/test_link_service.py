"""Entity links: one edge table, backlinks read in reverse, cascade on delete."""
import os
import tempfile
import unittest

from litebrowser.core import prefs
from litebrowser.services import (
    flashcard_service,
    history_service,
    link_service,
    personal_plan,
    personal_service,
    sync_service,
)


class TestLinkService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_backlinks_are_the_same_rows_read_in_reverse(self):
        note = personal_service.create_note(self.base, "OSI Model", "layers")
        item = personal_plan.create_item(self.base, "Ôn chương 3")
        link = link_service.add_link(
            self.base, "note", note["id"], "planner_item", item["id"], label="study"
        )
        self.assertTrue(link["id"])

        from_note = link_service.links_for(self.base, "note", note["id"])
        self.assertEqual(len(from_note["outgoing"]), 1)
        self.assertEqual(from_note["incoming"], [])
        from_item = link_service.links_for(self.base, "planner_item", item["id"])
        self.assertEqual(len(from_item["incoming"]), 1)
        self.assertEqual(from_item["incoming"][0]["label"], "study")
        self.assertEqual(from_item["total"], 1)

    def test_duplicate_and_invalid_links_are_refused(self):
        note = personal_service.create_note(self.base, "A", "")
        item = personal_plan.create_item(self.base, "B")
        first = link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])
        again = link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(link_service.load_links(self.base)), 1)

        self.assertIsNone(link_service.add_link(self.base, "note", note["id"], "note", note["id"]))
        self.assertIsNone(link_service.add_link(self.base, "bogus", note["id"], "note", note["id"]))
        self.assertEqual(link_service.delete_links_for(self.base, "note", ""), 0)

    def test_remove_link_reports_what_it_did(self):
        note = personal_service.create_note(self.base, "A", "")
        item = personal_plan.create_item(self.base, "B")
        link = link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])
        self.assertTrue(link_service.remove_link(self.base, link["id"]))
        self.assertFalse(link_service.remove_link(self.base, link["id"]))
        self.assertEqual(link_service.load_links(self.base), [])

    def test_deleting_entities_cascades_their_edges(self):
        note = personal_service.create_note(self.base, "A", "")
        item = personal_plan.create_item(self.base, "B")
        course = personal_plan.create_course(self.base, "Math")
        card = flashcard_service.add_card(self.base, "Q", "A")
        link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])
        link_service.add_link(self.base, "planner_course", course["id"], "note", note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"])

        personal_plan.delete_item(self.base, item["id"])
        self.assertEqual(link_service.links_for(self.base, "planner_item", item["id"])["total"], 0)

        personal_plan.delete_course(self.base, course["id"])
        self.assertEqual(link_service.links_for(self.base, "planner_course", course["id"])["total"], 0)

        self.assertTrue(flashcard_service.delete_card(self.base, card["id"]))
        self.assertEqual(link_service.links_for(self.base, "flashcard", card["id"])["total"], 0)

        # Deleting the note clears every remaining edge that touched it.
        self.assertTrue(personal_service.delete_note(self.base, note["id"]))
        self.assertEqual(link_service.load_links(self.base), [])

    def test_cards_for_a_note_take_their_edges_with_them(self):
        note = personal_service.create_note(self.base, "Topic", "")
        card = flashcard_service.add_card(self.base, "Q", "A", source_note_id=note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"])

        self.assertEqual(flashcard_service.delete_cards_for_note(self.base, note["id"]), 1)
        self.assertEqual(link_service.links_for(self.base, "note", note["id"])["total"], 0)

    def test_links_travel_in_backups_and_sync(self):
        note = personal_service.create_note(self.base, "A", "")
        item = personal_plan.create_item(self.base, "B")
        link = link_service.add_link(self.base, "note", note["id"], "planner_item", item["id"])

        payload = history_service.export_profile_payload(self.base)
        self.assertEqual([edge["id"] for edge in payload["entity_links"]], [link["id"]])

        dest = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile-dest"))
        self.assertTrue(history_service.import_profile_payload(dest, payload))
        self.assertEqual([edge["id"] for edge in link_service.load_links(dest)], [link["id"]])

        bundle = sync_service._bundle(self.base)
        self.assertIn("entity_links", bundle)
        self.assertEqual(sync_service._apply_bundle(dest, bundle)["links"], 1)


if __name__ == "__main__":
    unittest.main()
