"""Profile backup: JSON and ZIP bundle."""
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from litebrowser.core import prefs
from litebrowser.services import history_service, personal_service


class TestBackupExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_export_includes_session_state_vault_files(self):
        personal_service.create_note(self.base, "T", "b", category="C")
        payload = history_service.export_profile_payload(self.base)
        self.assertEqual(payload.get("backup_format_version"), 2)
        self.assertIn("session_state", payload)
        self.assertIsInstance(payload["session_state"], dict)
        self.assertIn("tabs", payload["session_state"])
        self.assertIn("vault_files", payload)
        self.assertIsInstance(payload["vault_files"], list)

    def test_zip_export_empty_vault_files_in_json(self):
        personal_service.create_note(self.base, "N", "body", category="X")
        zpath = os.path.join(self._tmp.name, "b.zip")
        self.assertTrue(history_service.export_profile_to_zip(self.base, zpath))
        with zipfile.ZipFile(zpath, "r") as zf:
            names = zf.namelist()
            self.assertIn(history_service.PROFILE_ZIP_JSON_MEMBER, names)
            raw = zf.read(history_service.PROFILE_ZIP_JSON_MEMBER).decode("utf-8")
        data = json.loads(raw)
        self.assertEqual(data.get("backup_format_version"), 3)
        self.assertEqual(data.get("backup_bundle"), "zip")
        self.assertEqual(data.get("vault_files"), [])

    def test_zip_roundtrip_restores_vault_file_and_note(self):
        vault = prefs.vault_path(self.base)
        os.makedirs(os.path.join(vault, "misc"), exist_ok=True)
        with open(os.path.join(vault, "misc", "blob.bin"), "wb") as f:
            f.write(b"\x00\x01\xFE")
        personal_service.create_note(self.base, "Keep", "hello", category="Cat")

        zpath = os.path.join(self._tmp.name, "full.zip")
        self.assertTrue(history_service.export_profile_to_zip(self.base, zpath))

        dest = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile2"))
        self.assertTrue(history_service.import_profile_from_path(dest, zpath))

        blob_path = os.path.join(prefs.vault_path(dest), "misc", "blob.bin")
        self.assertTrue(os.path.isfile(blob_path))
        with open(blob_path, "rb") as f:
            self.assertEqual(f.read(), b"\x00\x01\xFE")
        notes = personal_service.list_notes(dest)
        self.assertTrue(any(n.get("title") == "Keep" for n in notes))

    def test_zip_with_browser_data_roundtrip(self):
        from litebrowser.core import app_paths

        bd = app_paths.browser_data_path(self.base)
        os.makedirs(os.path.join(bd, "sub"), exist_ok=True)
        with open(os.path.join(bd, "sub", "marker.txt"), "w", encoding="utf-8") as f:
            f.write("webengine-test")

        zpath = os.path.join(self._tmp.name, "with-bd.zip")
        self.assertTrue(
            history_service.export_profile_to_zip(self.base, zpath, include_browser_data=True)
        )

        dest = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile-bd"))
        self.assertTrue(history_service.import_profile_from_path(dest, zpath))

        marker = os.path.join(app_paths.browser_data_path(dest), "sub", "marker.txt")
        self.assertTrue(os.path.isfile(marker))
        with open(marker, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "webengine-test")

    def test_browser_data_restore_rolls_back_if_final_swap_is_blocked(self):
        """A blocked directory rename must leave the pre-import profile intact."""
        from litebrowser.core import app_paths

        source_data = app_paths.browser_data_path(self.base)
        with open(os.path.join(source_data, "new.txt"), "w", encoding="utf-8") as f:
            f.write("new")
        zpath = os.path.join(self._tmp.name, "browser-data.zip")
        self.assertTrue(history_service.export_profile_to_zip(self.base, zpath, include_browser_data=True))

        dest = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile-swap-rollback"))
        dest_data = app_paths.browser_data_path(dest)
        old_marker = os.path.join(dest_data, "old.txt")
        with open(old_marker, "w", encoding="utf-8") as f:
            f.write("old")

        real_replace = history_service.os.replace

        def block_staging_swap(src, target):
            if (
                os.path.abspath(target) == os.path.abspath(dest_data)
                and os.path.basename(os.path.abspath(src)).startswith(".BrowserData.import-")
            ):
                raise PermissionError("simulated transient lock")
            return real_replace(src, target)

        with zipfile.ZipFile(zpath, "r") as zf, mock.patch.object(
            history_service.os, "replace", side_effect=block_staging_swap
        ):
            self.assertFalse(history_service._import_browser_data_from_zip(dest, zf))

        self.assertTrue(os.path.isfile(old_marker))
        self.assertFalse(os.path.exists(os.path.join(dest_data, "new.txt")))

    def test_import_rejects_path_traversal_note_ids(self):
        """A crafted backup must not write outside the notes dir (v6.5 fix)."""
        payload = history_service.export_profile_payload(self.base)
        payload["notes"] = [
            {"id": "../escaped.md", "content": "evil"},
            {"id": "C:/Windows/temp-evil.md", "content": "evil2"},
            {"id": "ok/note.md", "content": "fine"},
        ]
        zpath = os.path.join(self._tmp.name, "evil.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(history_service.PROFILE_ZIP_JSON_MEMBER, json.dumps(payload, ensure_ascii=False))

        dest = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile-traversal"))
        self.assertTrue(history_service.import_profile_from_path(dest, zpath))

        notes_root = os.path.abspath(personal_service.notes_dir(dest))
        escaped = os.path.abspath(os.path.join(notes_root, "..", "escaped.md"))
        self.assertFalse(os.path.isfile(escaped))
        self.assertFalse(os.path.isfile(os.path.join(notes_root, "escaped.md")))
        self.assertFalse(os.path.isfile(os.path.join(notes_root, "C:", "Windows", "temp-evil.md")))
        good = os.path.join(notes_root, "ok", "note.md")
        self.assertTrue(os.path.isfile(good))
        with open(good, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "fine")


if __name__ == "__main__":
    unittest.main()
