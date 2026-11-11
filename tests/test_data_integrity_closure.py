"""Closure regressions for encrypted backups and expanded recovery.

Every test uses a fresh temporary profile and a temporary backup destination.
No real profile, network endpoint or credential is touched.
"""
import os
import tempfile
import unittest
from unittest import mock

from litebrowser.core import prefs
from litebrowser.services import (
    backup_service,
    conflict_service,
    encrypted_backup_service,
    life_service,
    link_service,
    personal_plan,
    record_restore_service,
    restore_service,
    sync_service,
    tab_sets,
)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.dest = os.path.join(self._tmp.name, "backups")
        os.makedirs(self.dest, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _encrypted(self, password="correct horse battery"):
        result = encrypted_backup_service.create_encrypted_backup(
            self.base, password, destination=self.dest
        )
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.encrypted)
        return result


class TestEncryptedBackups(_Base):
    def test_round_trip_does_not_publish_plaintext(self):
        life_service.add_task(self.base, "Encrypted task")
        password = "correct horse battery"
        result = self._encrypted(password)
        self.assertTrue(result.path.endswith(encrypted_backup_service.EXTENSION))
        self.assertFalse(os.path.exists(result.path[:-4] + ".zip"))
        self.assertTrue(encrypted_backup_service.is_encrypted(result.path))
        checked = encrypted_backup_service.verify_encrypted(result.path, password)
        self.assertTrue(checked["ok"], checked["errors"])
        self.assertIn(
            "tasks.json", {row["path"] for row in checked["manifest"]["files"]}
        )
        with open(result.path, "rb") as handle:
            raw = handle.read()
        self.assertNotIn(password.encode("utf-8"), raw)
        self.assertNotIn(b"Encrypted task", raw)

    def test_wrong_password_and_tampering_fail_without_publishing(self):
        result = self._encrypted()
        wrong = encrypted_backup_service.verify_encrypted(result.path, "wrong password!!")
        self.assertFalse(wrong["ok"])
        self.assertEqual(wrong["status"], "authentication_failed")

        tampered = result.path + ".tampered"
        data = bytearray(open(result.path, "rb").read())
        data[-1] ^= 0x01
        with open(tampered, "wb") as handle:
            handle.write(data)
        checked = encrypted_backup_service.verify_encrypted(tampered, "correct horse battery")
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["status"], "authentication_failed")

    def test_truncated_and_bad_header_fail_before_restore(self):
        result = self._encrypted()
        truncated = result.path + ".short"
        data = open(result.path, "rb").read()
        with open(truncated, "wb") as handle:
            handle.write(data[:20])
        checked = encrypted_backup_service.verify_encrypted(truncated, "correct horse battery")
        self.assertFalse(checked["ok"])
        self.assertIn(checked["status"], {"truncated", "invalid_header", "unrecognised"})

        bad = result.path + ".badheader"
        with open(result.path, "rb") as source, open(bad, "wb") as target:
            target.write(source.read(len(encrypted_backup_service.MAGIC) + 4))
            target.write(b"{}")
        checked = encrypted_backup_service.verify_encrypted(bad, "correct horse battery")
        self.assertFalse(checked["ok"])

    def test_encrypted_restore_replaces_only_after_password_authentication(self):
        original = life_service.add_task(self.base, "Original")
        result = self._encrypted()
        life_service.add_task(self.base, "Current")
        preview = restore_service.preview(
            self.base, result.path, categories=["tasks"], password="correct horse battery"
        )
        self.assertTrue(preview["ok"], preview.get("error"))
        self.assertTrue(preview["encrypted"])
        restored = restore_service.restore(
            self.base,
            result.path,
            categories=["tasks"],
            confirm=True,
            password="correct horse battery",
        )
        self.assertTrue(restored.ok, restored.error)
        rows = life_service.load_tasks(self.base)
        self.assertEqual([row["id"] for row in rows], [original["id"]])
        self.assertEqual(rows[0]["title"], "Original")

    def test_wrong_password_does_not_modify_the_live_store(self):
        life_service.add_task(self.base, "Original")
        result = self._encrypted()
        current = life_service.add_task(self.base, "Current")
        refused = restore_service.restore(
            self.base,
            result.path,
            categories=["tasks"],
            confirm=True,
            password="wrong password!!",
        )
        self.assertFalse(refused.ok)
        self.assertEqual(refused.status, "authentication_failed")
        self.assertIn(current["id"], {row["id"] for row in life_service.load_tasks(self.base)})

    def test_legacy_backup_remains_importable_and_is_not_called_encrypted(self):
        life_service.add_task(self.base, "Legacy")
        legacy = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(legacy.ok, legacy.error)
        self.assertFalse(encrypted_backup_service.is_encrypted(legacy.path))
        checked = backup_service.verify_backup(legacy.path)
        self.assertTrue(checked["ok"], checked["errors"])
        self.assertFalse(checked.get("encrypted"))
        rows = backup_service.list_backups(self.dest)
        encrypted = [row for row in rows if row.get("encrypted")]
        self.assertEqual(encrypted, [])

    def test_encrypted_backup_is_listed_but_never_verified_without_a_password(self):
        result = self._encrypted()
        rows = backup_service.list_backups(self.dest, verify=True)
        row = next(row for row in rows if row["path"] == result.path)
        self.assertTrue(row["encrypted"])
        self.assertEqual(row["status"], "encrypted")
        self.assertFalse(row["verified"])
        self.assertIn("password", " ".join(row["errors"]).lower())


class TestHttpConflictClosure(_Base):
    def test_planner_conflict_is_archived_once_and_newer_remote_wins(self):
        course = personal_plan.create_course(self.base, "Course")
        item = personal_plan.create_item(self.base, "Local item", course_id=course["id"])
        local = {
            "id": item["id"],
            "title": "Local item",
            "course_id": course["id"],
            "updated_at": 100,
        }
        plan = personal_plan.load_plan(self.base)
        plan["items"] = [local]
        personal_plan.save_plan(self.base, plan)
        remote = {
            "id": item["id"],
            "title": "Remote item",
            "course_id": course["id"],
            "updated_at": 200,
        }
        sync_service._apply_bundle(self.base, {"personal_plan": {"items": [remote]}})
        rows = conflict_service.list_conflicts(self.base)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["store"], "planner")
        self.assertEqual(rows[0]["local"]["title"], "Local item")
        self.assertEqual(rows[0]["remote"]["title"], "Remote item")
        self.assertEqual(
            personal_plan.load_plan(self.base)["items"][0]["title"], "Remote item"
        )
        sync_service._apply_bundle(self.base, {"personal_plan": {"items": [remote]}})
        self.assertEqual(len(conflict_service.list_conflicts(self.base)), 1)

    def test_failed_planner_archive_keeps_local_row(self):
        item = personal_plan.create_item(self.base, "Local item")
        plan = personal_plan.load_plan(self.base)
        plan["items"] = [dict(item, title="Local item", updated_at=100)]
        personal_plan.save_plan(self.base, plan)
        remote = dict(item, title="Remote item", updated_at=200)
        with mock.patch.object(sync_service, "_archive_http_conflict", return_value=False):
            with self.assertRaises(sync_service.SyncMergeError) as raised:
                sync_service._apply_bundle(
                    self.base, {"personal_plan": {"items": [remote]}}
                )
        self.assertEqual(raised.exception.status, "ARCHIVE_FAILED")
        self.assertEqual(personal_plan.load_plan(self.base)["items"][0]["title"], "Local item")
        self.assertEqual(conflict_service.list_conflicts(self.base), [])

    def test_bookmark_divergence_is_archived_and_local_is_preserved(self):
        prefs.save_bookmarks(
            self.base,
            [{"title": "Local title", "url": "https://example.test/one", "folder": "A"}],
        )
        sync_service._apply_bundle(
            self.base,
            {
                "bookmarks": [
                    {"title": "Remote title", "url": "https://example.test/one", "folder": "B"},
                    {"title": "New", "url": "https://example.test/two"},
                ]
            },
        )
        self.assertEqual(
            {row["title"] for row in prefs.load_bookmarks(self.base)},
            {"Local title", "New"},
        )
        rows = conflict_service.list_conflicts(self.base)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["store"], "bookmarks")
        self.assertEqual(rows[0]["record_id"], "https://example.test/one")
        self.assertEqual(rows[0]["remote"]["title"], "Remote title")
        sync_service._apply_bundle(
            self.base,
            {
                "bookmarks": [
                    {"title": "Remote title", "url": "https://example.test/one", "folder": "B"}
                ]
            },
        )
        self.assertEqual(len(conflict_service.list_conflicts(self.base)), 1)


class TestRecordRestoreClosure(_Base):
    def test_bookmark_restore_uses_url_identity_and_rejects_as_new(self):
        prefs.save_bookmarks(
            self.base,
            [{"title": "Saved", "url": "https://example.test/saved", "folder": "Reading"}],
        )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        prefs.save_bookmarks(self.base, [])
        records = record_restore_service.list_records(result.path, "bookmarks")
        self.assertEqual(records[0]["id"], "https://example.test/saved")
        restored = record_restore_service.restore(
            self.base,
            result.path,
            "bookmarks",
            "https://example.test/saved",
            confirm=True,
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual(
            prefs.load_bookmarks(self.base)[0]["title"], "Saved"
        )
        with self.assertRaises(record_restore_service.RecordRestoreError):
            record_restore_service.restore(
                self.base,
                result.path,
                "bookmarks",
                "https://example.test/saved",
                mode="as_new",
                confirm=True,
            )

    def test_tab_set_restore_uses_store_semantics(self):
        created = tab_sets.add_tab_set(
            self.base,
            "collection",
            "Research set",
            [{"url": "https://example.test/article", "title": "Article"}],
        )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        tab_sets.remove_tab_set(self.base, created["id"])
        self.assertEqual(tab_sets.list_tab_sets(self.base), [])
        restored = record_restore_service.restore(
            self.base,
            result.path,
            "tab_sets",
            created["id"],
            confirm=True,
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        rows = tab_sets.list_tab_sets(self.base)
        self.assertEqual(rows[0]["title"], "Research set")
        self.assertEqual(rows[0]["tabs"][0]["url"], "https://example.test/article")

    def test_entity_link_restore_preserves_references(self):
        link = link_service.add_link(
            self.base, "task", "task-1", "note", "note-1", label="supports"
        )
        self.assertIsNotNone(link)
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        link_service.save_links(self.base, [])
        restored = record_restore_service.restore(
            self.base,
            result.path,
            "entity_links",
            link["id"],
            confirm=True,
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        rows = link_service.load_links(self.base)
        self.assertEqual(rows[0]["from_id"], "task-1")
        self.assertEqual(rows[0]["to_id"], "note-1")


if __name__ == "__main__":
    unittest.main()
