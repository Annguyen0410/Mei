"""Automated checks for workspace migration and prefs defaults (no Qt).

Manual smoke (after code changes): run ``python browser.py`` from repo root, then:
  - Both AppShell windows open; switch Home / Browser / Personal / AI / Library / History / Settings.
  - New tab, pin tab, close another tab; restart app and confirm session.
  - Save a page to Library; open Personal note; Ask AI once.
  - Export profile backup from History page and re-import on a test profile (optional).
"""
import json
import os
import tempfile
import unittest

from litebrowser.core import app_paths, prefs
from litebrowser.services import workspace_manager


class TestWorkspace(unittest.TestCase):
    def test_ensure_dual_workspaces_migrates_default_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "profile")
            os.makedirs(base, exist_ok=True)
            ws_path = prefs.workspaces_path(base)
            os.makedirs(os.path.dirname(ws_path), exist_ok=True)
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"workspaces": [{"id": "default", "name": "Old"}], "current_id": "default"},
                    f,
                )
            data = workspace_manager.ensure_dual_workspaces(base)
            ids = [w["id"] for w in data["workspaces"]]
            self.assertIn(workspace_manager.PRIMARY_WORKSPACE_ID, ids)
            self.assertIn(workspace_manager.SECONDARY_WORKSPACE_ID, ids)
            self.assertEqual(data["current_id"], workspace_manager.PRIMARY_WORKSPACE_ID)

    def test_load_workspaces_default_has_ws1_ws2(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "profile")
            os.makedirs(base, exist_ok=True)
            data = prefs.load_workspaces(base)
            ids = {w["id"] for w in data["workspaces"]}
            self.assertEqual(ids, {"ws1", "ws2"})
            self.assertEqual(data["current_id"], "ws1")

    def test_project_root_points_to_repo(self):
        root = app_paths.project_root()
        self.assertTrue(os.path.isfile(os.path.join(root, "browser.py")))
        self.assertTrue(os.path.isdir(os.path.join(root, "litebrowser")))

    def test_cuc_quan_ly_support_index_shipped(self):
        p = app_paths.cuc_quan_ly_support_index_path(None)
        self.assertTrue(p, "cuc_quan_ly_support_index_path should resolve")
        self.assertTrue(os.path.isfile(p), p)

    def test_boi_toan_local_launcher_is_shipped(self):
        url = app_paths.bundled_site_url("boitoan", None)
        self.assertTrue(url.startswith("file://"), url)
        self.assertTrue(url.endswith("index.html"), url)

    def test_personal_site_defaults_use_deployed_project_links(self):
        sites = {item["key"]: item["url"] for item in app_paths.chain_remote_sites(None)}
        self.assertEqual(
            sites,
            {
                "linklumina": "https://graceful-kangaroo-4ebbee.netlify.app",
                "cucquanly": "https://starlit-lily-f90e23.netlify.app",
                "mas": "https://mahoraga-adapt-system-mas-v9-0.onrender.com",
                "boitoan": "https://boitoanzaigame.netlify.app",
                "worldleaderboard": "https://worldleaderboard.netlify.app",
                "bimat": "https://personalfrequencys.netlify.app",
            },
        )

    def test_browser_data_saver_preference_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = prefs.ensure_profile_layout(os.path.join(tmp, "profile"))
            self.assertFalse(prefs.get_browser_data_saver(base))
            prefs.set_browser_data_saver(base, True)
            self.assertTrue(prefs.get_browser_data_saver(base))
            prefs.set_browser_data_saver(base, False)
            self.assertFalse(prefs.get_browser_data_saver(base))


if __name__ == "__main__":
    unittest.main()
