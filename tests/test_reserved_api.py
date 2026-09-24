"""Reserved API: capabilities that exist in the data layer (and are reachable
from the phone bridge, the sync bundle or a future UI) but have no desktop
caller yet.

These functions are deliberately kept rather than deleted, so they must be
exercised: the capability ledger in ``docs/CAPABILITIES.md`` lists them, and this
file is what keeps them honest. Anything NOT listed there and still unreferenced
should be deleted instead.
"""
import os
import tempfile
import unittest
from unittest import mock

from litebrowser.core import app_paths, prefs
from litebrowser.services import (
    brief_service,
    google_auth,
    page_monitor,
    personal_plan,
    tab_sets,
    workspace_manager,
)


class _ProfileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()


class TestPlannerCourseLifecycle(_ProfileCase):
    def test_course_can_be_created_renamed_and_deleted(self):
        course = personal_plan.create_course(self.base, "Giải tích")
        self.assertTrue(course["id"])

        renamed = personal_plan.update_course(self.base, course["id"], name="Giải tích 2")
        self.assertEqual(renamed["name"], "Giải tích 2")
        stored = personal_plan.load_plan(self.base)["courses"]
        self.assertEqual([c["name"] for c in stored], ["Giải tích 2"])

        self.assertTrue(personal_plan.delete_course(self.base, course["id"]))
        self.assertEqual(personal_plan.load_plan(self.base)["courses"], [])

    def test_deleting_a_course_detaches_items_and_blocks(self):
        course = personal_plan.create_course(self.base, "Vật lý")
        item = personal_plan.create_item(self.base, "Ôn chương 1", course_id=course["id"])
        block = personal_plan.create_time_block(
            self.base, "Tự học", personal_plan._today(), 540, course_id=course["id"]
        )

        personal_plan.delete_course(self.base, course["id"])
        plan = personal_plan.load_plan(self.base)
        self.assertEqual([i for i in plan["items"] if i["id"] == item["id"]][0]["course_id"], "")
        self.assertEqual([b for b in plan["time_blocks"] if b["id"] == block["id"]][0]["course_id"], "")

    def test_unknown_ids_are_reported_not_crashed(self):
        self.assertIsNone(personal_plan.update_course(self.base, "nope", name="x"))
        self.assertFalse(personal_plan.delete_course(self.base, "nope"))
        self.assertIsNone(personal_plan.update_time_block(self.base, "nope", duration_minutes=30))


class TestPlannerReservedHelpers(_ProfileCase):
    def test_save_plan_normalizes_and_persists(self):
        personal_plan.save_plan(self.base, {"items": [{"title": "Read", "kind": "bogus"}]})
        plan = personal_plan.load_plan(self.base)
        self.assertEqual(plan["items"][0]["title"], "Read")
        self.assertNotEqual(plan["items"][0]["kind"], "bogus")

    def test_plan_settings_persist(self):
        personal_plan.update_plan_settings(
            self.base,
            semester={"name": "HK1", "start_date": "2026-09-01", "end_date": "2027-01-15"},
        )
        semester = personal_plan.load_plan(self.base)["semester"]
        self.assertEqual(semester["name"], "HK1")
        self.assertEqual(semester["start_date"], "2026-09-01")

    def test_time_block_can_be_edited(self):
        block = personal_plan.create_time_block(self.base, "Tự học", personal_plan._today(), 600)
        updated = personal_plan.update_time_block(self.base, block["id"], duration_minutes=90)
        self.assertEqual(updated["duration_minutes"], 90)


class TestPageMonitorRemoval(_ProfileCase):
    def test_monitor_can_be_added_then_removed(self):
        monitor = page_monitor.add_monitor(self.base, "https://example.com/page", "Example")
        self.assertEqual(len(page_monitor.load_monitors(self.base)), 1)

        page_monitor.remove_monitor(self.base, monitor["id"])
        self.assertEqual(page_monitor.load_monitors(self.base), [])
        self.assertEqual(page_monitor.due_monitors(self.base), [])


class TestRenames(_ProfileCase):
    def test_tab_set_rename(self):
        tab_set = tab_sets.add_tab_set(self.base, "search", "Old name", [{"title": "A", "url": "https://a"}])
        self.assertTrue(tab_sets.rename_tab_set(self.base, tab_set["id"], "New name"))
        self.assertEqual(tab_sets.get_tab_set(self.base, tab_set["id"])["title"], "New name")

    def test_tab_set_rename_validates_input(self):
        tab_set = tab_sets.add_tab_set(self.base, "search", "Old name", [{"title": "A", "url": "https://a"}])
        self.assertFalse(tab_sets.rename_tab_set(self.base, tab_set["id"], "   "))
        self.assertEqual(tab_sets.get_tab_set(self.base, tab_set["id"])["title"], "Old name")

    def test_workspace_rename(self):
        workspace_manager.ensure_dual_workspaces(self.base)
        target = workspace_manager.get_workspaces_list(self.base)[0]
        self.assertTrue(workspace_manager.rename_workspace(self.base, target["id"], "Renamed"))
        names = [w["name"] for w in workspace_manager.get_workspaces_list(self.base)]
        self.assertIn("Renamed", names)
        self.assertFalse(workspace_manager.rename_workspace(self.base, "nope", "x"))


class TestGoogleTokenLifecycle(_ProfileCase):
    def test_token_cache_round_trip(self):
        # Written after sign-in, read back by the refresh path below.
        prefs.set_google_token_cache(self.base, {"access_token": "a", "expires_in": 3600, "obtained_at": 1})
        self.assertEqual(prefs.get_google_token_cache(self.base)["access_token"], "a")

    def test_fresh_token_is_reused_without_network(self):
        import time as _time

        cached = {"access_token": "live", "refresh_token": "r", "expires_in": 3600, "obtained_at": int(_time.time())}
        with mock.patch.object(google_auth, "_json_post") as post:
            self.assertEqual(google_auth.ensure_valid_token("cid", cached)["access_token"], "live")
        post.assert_not_called()

    def test_no_cache_means_no_token(self):
        self.assertIsNone(google_auth.ensure_valid_token("cid", None))
        self.assertIsNone(google_auth.ensure_valid_token("cid", {}))

    def test_expired_token_is_refreshed(self):
        import time as _time

        cached = {
            "access_token": "stale",
            "refresh_token": "refresh-me",
            "expires_in": 3600,
            "obtained_at": int(_time.time()) - 7200,
        }
        with mock.patch.object(
            google_auth, "_json_post", return_value={"access_token": "fresh", "expires_in": 3600}
        ):
            refreshed = google_auth.ensure_valid_token("cid", cached)
        self.assertEqual(refreshed["access_token"], "fresh")

    def test_expired_token_without_refresh_is_dropped(self):
        import time as _time

        stale = {"access_token": "stale", "expires_in": 3600, "obtained_at": int(_time.time()) - 7200}
        self.assertIsNone(google_auth.ensure_valid_token("cid", stale))


class TestGoogleDeviceFlow(_ProfileCase):
    def test_sign_in_helper_runs_both_steps(self):
        device = {"device_code": "d", "user_code": "u"}
        with mock.patch.object(google_auth, "request_device_code", return_value=device) as request, mock.patch.object(
            google_auth, "poll_device_token", return_value={"access_token": "t"}
        ) as poll:
            result = google_auth.sign_in_via_device_code("cid", None)
        self.assertEqual(result, {"access_token": "t"})
        request.assert_called_once_with("cid")
        poll.assert_called_once_with("cid", device)

    def test_sign_in_helper_propagates_denial(self):
        with mock.patch.object(google_auth, "request_device_code", return_value={"device_code": "d"}), mock.patch.object(
            google_auth, "poll_device_token", return_value=None
        ):
            self.assertIsNone(google_auth.sign_in_via_device_code("cid", None))


class TestPasscodeLock(_ProfileCase):
    def test_lock_clears_the_unlocked_state(self):
        from litebrowser.services import security

        self.assertFalse(security.is_unlocked(self.base))
        security.set_passcode(self.base, "1234")
        self.assertTrue(security.verify_passcode(self.base, "1234"))
        self.assertFalse(security.verify_passcode(self.base, "9999"))
        security.lock(self.base)
        self.assertFalse(security.is_unlocked(self.base))


class TestBriefRendering(_ProfileCase):
    def test_markdown_renders_every_section(self):
        brief = {
            "headline": "Midday Brew",
            "date": "Monday, 01 September 2026",
            "yesterday_count": 12,
            "top_domains": [("docs.python.org", 5)],
            "today_visits": 3,
            "focus_minutes": 50,
            "notes_count": 7,
            "overdue_tasks": ["Pay rent"],
            "due_today": ["Essay"],
            "upcoming_events": [{"starts_at": 1790000000, "title": "Lab"}],
            "pending_tasks": 4,
        }
        markdown = brief_service.brief_markdown(brief)
        for expected in ("# ☕", "docs.python.org", "## ⏰ Overdue", "## 📌 Due today", "## 📅 Coming up", "Lab"):
            with self.subTest(expected=expected):
                self.assertIn(expected, markdown)

    def test_live_brief_has_headline_and_text(self):
        brief = brief_service.build_morning_brief(self.base)
        self.assertTrue(brief.get("headline"))
        self.assertTrue(brief_service.brief_text(brief))
        self.assertTrue(brief_service.brief_markdown(brief))


class TestSupportUrl(_ProfileCase):
    def test_cuc_quan_ly_url_matches_its_index_when_present(self):
        index = app_paths.cuc_quan_ly_support_index_path()
        url = app_paths.cuc_quan_ly_support_url()
        if not index:
            self.assertEqual(url, "")
            self.skipTest("no bundled Cục Quản Lý copy on this machine")
        self.assertTrue(url.startswith("file://"))
        self.assertTrue(url.endswith("index.html"))


if __name__ == "__main__":
    unittest.main()
