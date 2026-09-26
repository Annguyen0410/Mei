"""The loop seen from every plane: backup, sync, AI index, brief, cascades.

These are the cross-cutting contracts the loop leans on. A recommendation is only
worth showing if the same graph survives a backup round-trip, a self-hosted sync
merge and an AI reindex — and if deleting either end of a link never leaves a
dangling edge behind.
"""
import os
import tempfile
import unittest
import zipfile

from litebrowser.core import prefs
from litebrowser.services import (
    ai_service,
    brief_service,
    flashcard_service,
    history_service,
    life_service,
    link_service,
    personal_plan,
    personal_service,
    study_flow,
    sync_service,
)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def _fresh_profile(self, name: str) -> str:
        return prefs.ensure_profile_layout(os.path.join(self._tmp.name, name))


class TestLoopAcrossPlanes(_Base):
    def test_zip_backup_round_trips_the_link_graph(self):
        note = personal_service.create_note(self.base, "OSI Model", "# OSI\n\n7 layers")
        card = flashcard_service.add_card(self.base, "Layers?", "7", source_note_id=note["id"])
        task = life_service.add_task(self.base, "Write lab report")
        item = study_flow.promote_task(self.base, task["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"], label="made from")

        zpath = os.path.join(self._tmp.name, "loop.zip")
        self.assertTrue(history_service.export_profile_to_zip(self.base, zpath))
        with zipfile.ZipFile(zpath, "r") as zf:
            payload = zf.read("profile.json").decode("utf-8")
        self.assertIn("entity_links", payload)

        dest = self._fresh_profile("profile-restored")
        self.assertTrue(history_service.import_profile_from_path(dest, zpath))

        self.assertEqual(len(link_service.load_links(dest)), 2)
        restored = link_service.links_for(dest, "planner_item", item["id"])
        self.assertEqual(restored["incoming"][0]["from_id"], task["id"])
        self.assertEqual(link_service.links_for(dest, "note", note["id"])["total"], 1)

    def test_an_older_backup_without_entity_links_keeps_the_local_graph(self):
        note = personal_service.create_note(self.base, "Keep", "body")
        card = flashcard_service.add_card(self.base, "Q", "A", source_note_id=note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"])
        payload = history_service.export_profile_payload(self.base)
        payload.pop("entity_links")

        dest = self._fresh_profile("profile-old")
        link_service.add_link(dest, "flashcard", "keep-card", "note", "keep-note")
        self.assertTrue(history_service.import_profile_payload(dest, payload))
        self.assertEqual(len(link_service.load_links(dest)), 1)
        self.assertEqual(link_service.load_links(dest)[0]["to_id"], "keep-note")

    def test_sync_bundle_exports_link_rows(self):
        note = personal_service.create_note(self.base, "Clip", "body")
        card = flashcard_service.add_card(self.base, "Q", "A", source_note_id=note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"])
        bundle = sync_service._bundle(self.base)
        self.assertEqual(len(bundle["entity_links"]), 1)
        self.assertEqual(bundle["entity_links"][0]["from_type"], "flashcard")

    def test_sync_pull_merges_remote_links_without_losing_local_ones(self):
        note = personal_service.create_note(self.base, "Local", "body")
        link_service.add_link(self.base, "note", note["id"], "flashcard", "local-card")
        applied = sync_service._apply_bundle(
            self.base,
            {
                "entity_links": [
                    {"id": "remote-link", "from_type": "note", "from_id": "r", "to_type": "flashcard", "to_id": "c"},
                    {"from_type": "bogus", "from_id": "x", "to_type": "note", "to_id": "y"},
                ]
            },
        )
        # The applied counter counts incoming dict rows; the store's normaliser is
        # what drops the row with an unknown entity type (and it must not raise).
        self.assertEqual(applied["links"], 2)
        self.assertEqual(len(link_service.load_links(self.base)), 2)
        self.assertEqual(
            {link["id"] for link in link_service.load_links(self.base)},
            {link_service.load_links(self.base)[0]["id"], "remote-link"},
        )

    def test_ai_index_carries_the_next_step(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        docs = ai_service.collect_docs(self.base)
        flow_docs = [doc for doc in docs if doc.source == "flow"]
        self.assertEqual(len(flow_docs), 1)
        action = study_flow.next_step(self.base)
        self.assertIn(action["label"], flow_docs[0].title)
        self.assertEqual(flow_docs[0].meta["step"], "study")
        self.assertEqual(flow_docs[0].meta["entity_id"], action["id"])

    def test_ai_index_flow_doc_survives_a_rebuild(self):
        life_service.add_task(self.base, "Inbox row", bucket="today")
        ai_service.rebuild_index(self.base)
        docs = ai_service.load_index(self.base)["docs"]
        self.assertEqual([doc["source"] for doc in docs if doc["source"] == "flow"], ["flow"])

    def test_brief_carries_the_same_next_step_as_home(self):
        personal_plan.create_item(self.base, "Late essay", due_date="2020-01-01")
        brief = brief_service.build_morning_brief(self.base)
        action = study_flow.next_step(self.base)
        self.assertEqual(brief["next_step"], action)
        self.assertIn(action["label"], brief_service.brief_text(brief))
        self.assertIn("## ▶ Next step", brief_service.brief_markdown(brief))

    def test_brief_next_step_follows_the_loop_as_the_day_moves(self):
        brief_before = brief_service.build_morning_brief(self.base)
        self.assertEqual(brief_before["next_step"]["step"], "plan")
        study_flow.promote_task(self.base, life_service.add_task(self.base, "Row", bucket="today")["id"])
        item = personal_plan.create_item(self.base, "Read ch.5", due_date="2020-01-01")
        self.assertEqual(brief_service.build_morning_brief(self.base)["next_step"]["id"], item["id"])

    def test_agenda_and_flow_point_at_the_same_row(self):
        item = personal_plan.create_item(self.base, "Read ch.5", scheduled_date=personal_plan._today())
        agenda = life_service.today_agenda(self.base)
        self.assertEqual([entry["id"] for entry in agenda["items"]], [item["id"]])
        self.assertEqual(study_flow.next_step(self.base)["id"], item["id"])


class TestCascadeMatrix(_Base):
    """Deleting either end of an edge must leave the graph clean."""

    def setUp(self):
        super().setUp()
        self.note = personal_service.create_note(self.base, "Source note", "body")
        self.card = flashcard_service.add_card(self.base, "Q", "A", source_note_id=self.note["id"])
        link_service.add_link(self.base, "flashcard", self.card["id"], "note", self.note["id"])
        self.item = personal_plan.create_item(self.base, "Essay")
        link_service.add_link(self.base, "planner_item", self.item["id"], "note", self.note["id"])

    def test_deleting_a_planner_item_drops_only_its_edges(self):
        self.assertTrue(personal_plan.delete_item(self.base, self.item["id"]))
        self.assertEqual(len(link_service.load_links(self.base)), 1)
        self.assertEqual(link_service.links_for(self.base, "note", self.note["id"])["total"], 1)

    def test_deleting_a_note_takes_its_cards_and_edges(self):
        self.assertEqual(flashcard_service.delete_cards_for_note(self.base, self.note["id"]), 1)
        personal_service.delete_note(self.base, self.note["id"])
        self.assertEqual(link_service.load_links(self.base), [])
        self.assertEqual(flashcard_service.load_cards(self.base), [])

    def test_deleting_a_card_drops_the_edge_but_keeps_the_note(self):
        self.assertTrue(flashcard_service.delete_card(self.base, self.card["id"]))
        remaining = link_service.load_links(self.base)
        self.assertEqual(len(remaining), 1, "only the planner→note edge should survive")
        self.assertEqual(remaining[0]["from_type"], "planner_item")
        self.assertIsNotNone(personal_service.read_note(self.base, self.note["id"]))

    def test_deleting_a_block_or_course_drops_their_edges(self):
        block = personal_plan.create_time_block(self.base, "Block", personal_plan._today(), 540)
        link_service.add_link(self.base, "planner_block", block["id"], "note", self.note["id"])
        course = personal_plan.create_course(self.base, "Giải tích")
        link_service.add_link(self.base, "planner_course", course["id"], "note", self.note["id"])
        self.assertEqual(len(link_service.load_links(self.base)), 4)

        self.assertTrue(personal_plan.delete_time_block(self.base, block["id"]))
        self.assertEqual(link_service.links_for(self.base, "planner_block", block["id"])["total"], 0)
        self.assertTrue(personal_plan.delete_course(self.base, course["id"]))
        self.assertEqual(link_service.links_for(self.base, "planner_course", course["id"])["total"], 0)
        # The note keeps the two edges that never pointed at the deleted rows.
        self.assertEqual(link_service.links_for(self.base, "note", self.note["id"])["total"], 2)

    def test_a_promoted_task_link_outlives_a_deleted_item_only_as_far_as_the_graph(self):
        task = life_service.add_task(self.base, "Row", bucket="today")
        item = study_flow.promote_task(self.base, task["id"])
        self.assertTrue(personal_plan.delete_item(self.base, item["id"]))
        self.assertEqual(link_service.links_for(self.base, "task", task["id"])["total"], 0)
        self.assertEqual(len(life_service.load_tasks(self.base)), 1, "the inbox row survives")

    def test_cascading_an_entity_with_no_edges_is_a_no_op(self):
        self.assertEqual(link_service.delete_links_for(self.base, "note", "missing"), 0)
        self.assertEqual(link_service.delete_links_for(self.base, "bogus", "missing"), 0)
        self.assertEqual(len(link_service.load_links(self.base)), 2)


class TestUnifiedLoopScenario(_Base):
    """One pass through capture → plan → study → review → reflect."""

    def _expire_running_pour(self, seconds: int = 1500):
        import json
        import time

        from litebrowser.services import focus_service

        path = focus_service.sessions_path(self.base)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        now = int(time.time())
        data["active"]["started_at"] = now - seconds
        data["active"]["ends_at"] = now - 1
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        focus_service.focus_status(self.base)

    def test_the_whole_loop_moves_between_stores(self):
        # 1. Capture — a clipped page lands in the reading list, a note and a task follow.
        page = life_service.add_saved_page(self.base, "BFS vs DFS", "https://example.com/graphs")
        note = personal_service.create_note(
            self.base, "BFS vs DFS", "# BFS vs DFS\n\n> queue vs stack\n", category="Clippings"
        )
        task = life_service.add_task(self.base, "Summarise graph notes", bucket="today")
        self.assertTrue(page["id"] and note["id"] and task["id"])

        # 2. Plan — the inbox row is the loudest capture, so the loop asks for it first.
        plan_step = study_flow.next_step(self.base)
        self.assertEqual(plan_step["step"], "plan")
        self.assertEqual(plan_step["id"], task["id"])
        item = study_flow.promote_task(self.base, task["id"], due_date=personal_plan._today())
        self.assertEqual(item["title"], "Summarise graph notes")
        self.assertEqual(link_service.links_for(self.base, "task", task["id"])["total"], 1)

        # 3. Study — the loop now points at the plan, and the pour credits the item.
        study = study_flow.next_step(self.base)
        self.assertEqual(study["step"], "study")
        self.assertEqual(study["id"], item["id"])
        from litebrowser.services import study_session

        session = study_session.start_for_item(self.base, item["id"], study["minutes"])
        self.assertEqual(session["item_id"], item["id"])
        self._expire_running_pour(1500)
        credited = study_session.credit_pending(self.base)
        self.assertEqual(credited["credited"], 1)
        self.assertGreater(credited["minutes"], 0)
        stored = personal_plan.load_plan(self.base)["items"][0]
        self.assertEqual(stored["studied_minutes"], credited["minutes"])
        self.assertTrue(stored["last_studied_at"])
        # Ticking the row off in the planner is what moves the loop on; until then
        # the same item is still today's work.
        self.assertEqual(study_flow.next_step(self.base)["id"], item["id"])
        personal_plan.complete_item(self.base, item["id"], True)

        # 4. Capture — the clipped note is the only thing left without recall material.
        capture = study_flow.next_step(self.base)
        self.assertEqual(capture["step"], "capture")
        self.assertEqual(capture["id"], note["id"])
        card = flashcard_service.add_card(self.base, "BFS uses?", "a queue", source_note_id=note["id"])
        link_service.add_link(self.base, "flashcard", card["id"], "note", note["id"], label="made from")
        self.assertEqual(study_flow.build_flow(self.base)["counts"]["capture"], 0)

        # 5. Review — the fresh card is due immediately.
        review = study_flow.next_step(self.base)
        self.assertEqual(review["step"], "review")
        self.assertEqual(review["label"], "🧠 Review 1 due card(s)")
        graded = flashcard_service.review_card(self.base, card["id"], "good")
        self.assertIsNotNone(graded)
        self.assertEqual(flashcard_service.stats(self.base)["due"], 0)

        # 6. Reflect — nothing pending, so the loop invites a plan and the brief agrees.
        final = study_flow.build_flow(self.base)
        self.assertEqual(final["next"]["step"], "plan")
        self.assertEqual(final["counts"]["review"], 0)
        self.assertEqual(final["counts"]["reflect"], 2, "card→note and task→planner edges")
        self.assertIn(
            final["next"]["label"],
            brief_service.brief_text(brief_service.build_morning_brief(self.base)),
        )
        self.assertEqual(final["counts"]["study"], 0, "the promoted item carries study credit")


if __name__ == "__main__":
    unittest.main()
