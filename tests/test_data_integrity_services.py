"""Data-integrity regressions: corruption, migrations, backup/restore, recovery.

Every test uses a fresh temporary profile.  No real profile, backup destination
or network resource is touched.
"""
import hashlib
import json
import os
import tempfile
import time
import unittest
import zipfile
from unittest import mock

from litebrowser.core import migration_journal, prefs, storage_health
from litebrowser.core import storage_catalog
from litebrowser.core.storage_utils import damaged_paths, read_json, write_json
from litebrowser.core.store import StoreReadError, StoreSpec, StoreWriteError, read_store, write_store
from litebrowser.services import (
    backup_scheduler,
    backup_service,
    conflict_service,
    integrity_service,
    life_service,
    personal_service,
    record_restore_service,
    recovery_service,
    restore_service,
)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.dest = os.path.join(self._tmp.name, "backups")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data):
        path = os.path.join(self.base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if mode == "wb" else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as handle:
            handle.write(data)
        return path


class TestStorageHealth(_Base):
    def test_read_statuses_are_distinct(self):
        self.assertEqual(storage_health.read_json_checked(os.path.join(self.base, "none.json")).status, "missing")
        self._write("empty.json", "")
        self.assertEqual(storage_health.read_json_checked(os.path.join(self.base, "empty.json")).status, "empty")
        self._write("bad.json", b"\xff\xfe")
        self.assertEqual(storage_health.read_json_checked(os.path.join(self.base, "bad.json")).status, "invalid_encoding")
        self._write("broken.json", "{oops")
        self.assertEqual(storage_health.read_json_checked(os.path.join(self.base, "broken.json")).status, "malformed_json")
        self._write("list.json", "[]")
        self.assertEqual(
            storage_health.read_json_checked(os.path.join(self.base, "list.json"), dict).status,
            "wrong_root_type",
        )

    def test_quarantine_preserves_source_and_never_overwrites(self):
        path = self._write("broken.json", "{not json")
        first = storage_health.quarantine_file(self.base, path, category="test", reason="malformed")
        second = storage_health.quarantine_file(self.base, path, category="test", reason="malformed")
        self.assertEqual(open(path, encoding="utf-8").read(), "{not json")
        self.assertNotEqual(first["artifact"], second["artifact"])
        artifact = os.path.join(self.base, "Recovery", "quarantine", first["artifact"])
        self.assertEqual(open(artifact, encoding="utf-8").read(), "{not json")
        self.assertTrue(os.path.isfile(artifact + ".json"))
        self.assertTrue(first["source_preserved"])

    def test_legacy_store_is_preserved_and_cannot_be_overwritten(self):
        path = self._write("legacy.json", "{broken")
        self.assertEqual(read_json(path, {}), {})
        with self.assertRaises(OSError):
            write_json(path, {"replacement": True})
        self.assertEqual(open(path, encoding="utf-8").read(), "{broken")
        self.assertIn(os.path.normcase(os.path.abspath(path)), damaged_paths())
        copies = [name for name in os.listdir(self.base) if ".corrupt-" in name]
        self.assertEqual(len(copies), 1)
        self.assertEqual(open(os.path.join(self.base, copies[0]), encoding="utf-8").read(), "{broken")

    def test_quarantine_refuses_a_path_outside_the_profile(self):
        outside = os.path.join(self._tmp.name, "outside.json")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(storage_health.StorageHealthError):
            storage_health.quarantine_file(self.base, outside, category="x", reason="x")

    def test_store_inventory_distinguishes_empty_from_corrupt(self):
        life_service.save_tasks(self.base, [])
        self.assertTrue(all(row["available"] for row in storage_health.store_health(self.base)))
        self._write("tasks.json", "{broken")
        rows = storage_health.store_health(self.base)
        tasks = next(row for row in rows if row["name"] == "tasks.json")
        self.assertFalse(tasks["available"])
        self.assertEqual(tasks["status"], "malformed_json")
        self.assertEqual(storage_health.unavailable_stores(self.base)[0]["name"], "tasks.json")
        summary = storage_health.health_summary(self.base)
        self.assertFalse(summary["healthy"])
        self.assertEqual(summary["unavailable_count"], 1)

    def test_write_guard_protects_a_store_before_it_is_read(self):
        path = self._write("background.json", "{broken")
        with self.assertRaises(OSError):
            write_json(path, {"would": "replace"})
        self.assertEqual(open(path, encoding="utf-8").read(), "{broken")
        self.assertTrue(any(".corrupt-" in name for name in os.listdir(self.base)))

    def test_migration_coverage_is_explicit_for_every_catalogued_store(self):
        coverage = storage_catalog.migration_coverage()
        self.assertEqual(coverage["total"], len(storage_catalog.STORES))
        self.assertEqual(coverage["journaled"], 3)
        self.assertEqual(
            {row["name"] for row in coverage["stores"] if row["manager"] == "storespec"},
            set(storage_catalog.JOURNALED_STORES),
        )
        self.assertTrue(all(row["journal"] and row["recovery"] for row in coverage["stores"]))
        self.assertEqual(coverage["notes"]["manager"], "file-store")


class TestCorruptStoresAndJournal(_Base):
    def test_corrupt_store_raises_and_quarantines(self):
        spec = StoreSpec(name="fake.json", version=1, default=lambda: {"rows": []})
        path = os.path.join(self.base, spec.name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with self.assertRaises(StoreReadError) as caught:
            read_store(self.base, spec)
        self.assertEqual(caught.exception.status, "malformed_json")
        self.assertEqual(open(path, encoding="utf-8").read(), "{broken")
        with self.assertRaises(StoreWriteError):
            write_store(self.base, spec, {"rows": []})
        self.assertEqual(open(path, encoding="utf-8").read(), "{broken")

    def test_migration_is_journaled_with_a_snapshot(self):
        name = "journaled.json"
        spec = StoreSpec(
            name=name,
            version=2,
            default=lambda: {"rows": []},
            migrate=lambda data, _version: {"rows": data.get("rows", []) + ["migrated"]},
        )
        path = os.path.join(self.base, name)
        original = json.dumps({"version": 1, "rows": ["a"]})
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(original)
        self.assertEqual(read_store(self.base, spec)["rows"], ["a", "migrated"])
        entry = migration_journal.entries(self.base)[-1]
        self.assertEqual(entry["state"], migration_journal.COMMITTED)
        snapshot = os.path.join(self.base, entry["snapshot"])
        self.assertEqual(open(snapshot, encoding="utf-8").read(), original)
        self.assertGreater(len(entry["input_sha256"]), 10)
        self.assertGreater(len(entry["output_sha256"]), 10)

    def test_crash_after_replacement_is_reconciled_as_committed(self):
        name = "crash.json"
        spec = StoreSpec(
            name=name,
            version=2,
            default=lambda: {"rows": []},
            migrate=lambda data, _version: {"rows": data.get("rows", []) + ["new"]},
        )
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "rows": ["old"]}, handle)
        real_commit = migration_journal.mark_committed
        with mock.patch.object(migration_journal, "mark_committed", side_effect=OSError("crash window")):
            read_store(self.base, spec)
        # The replacement landed; the journal could not be closed in that call.
        self._write(name, json.dumps({"version": 2, "rows": ["old", "new"]}))
        self.assertEqual(migration_journal.entries(self.base)[-1]["state"], migration_journal.RECOVERY_REQUIRED)
        results = migration_journal.reconcile(self.base)
        self.assertEqual(results[-1].state, migration_journal.COMMITTED)
        self.assertEqual(migration_journal.entries(self.base)[-1]["state"], migration_journal.COMMITTED)
        self.assertTrue(real_commit)

    def test_failed_replacement_leaves_source_and_recovery_snapshot(self):
        name = "failed.json"
        spec = StoreSpec(
            name=name,
            version=2,
            default=lambda: {"rows": []},
            migrate=lambda data, _version: {"rows": ["new"]},
        )
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "rows": ["keep"]}, handle)
        from litebrowser.core import store as store_module

        with mock.patch.object(store_module, "write_json", side_effect=OSError("disk full")):
            payload = read_store(self.base, spec)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(json.load(open(path, encoding="utf-8"))["version"], 1)
        entry = migration_journal.entries(self.base)[-1]
        self.assertEqual(entry["state"], migration_journal.RECOVERY_REQUIRED)
        self.assertTrue(os.path.isfile(os.path.join(self.base, entry["snapshot"])))


def _make_backup(path, files, *, status="complete", format_version=1, created_at=1700000000, extra_paths=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    manifest = {
        "kind": "mei.profile_backup",
        "format_version": format_version,
        "backup_id": "fixture",
        "created_at": created_at,
        "mei_version": "test",
        "profile_id": "test",
        "status": status,
        "files": [
            {
                "path": name,
                "category": "tasks" if name.endswith(".json") else "notes",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in files.items()
        ],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(backup_service.MANIFEST_NAME, json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
        for name, data in (extra_paths or {}).items():
            archive.writestr(name, data)
    return path


class TestBackupService(_Base):
    def test_backup_is_verified_and_excludes_secrets_and_browser_data(self):
        life_service.add_task(self.base, "Keep me")
        personal_service.create_note(self.base, "Note", "body text")
        prefs.save_pref(self.base, "password", "hunter2")
        self._write("secrets.dat", b"secret bytes")
        self._write("proxy_config.json", '{"password":"hunter2"}')
        self._write("BrowserData/Cookies", b"cookie")
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        checked = backup_service.verify_backup(result.path)
        self.assertTrue(checked["ok"], checked["errors"])
        with zipfile.ZipFile(result.path) as archive:
            names = archive.namelist()
            prefs_bytes = archive.read("prefs.json")
        self.assertNotIn("secrets.dat", names)
        self.assertNotIn("proxy_config.json", names)
        self.assertFalse(any(name.startswith("BrowserData/") for name in names))
        self.assertNotIn(b"hunter2", prefs_bytes)
        self.assertTrue(any(name.startswith("SafeVault/notes/") for name in names))

    def test_backup_destination_inside_the_profile_is_refused(self):
        result = backup_service.create_backup(self.base, destination=os.path.join(self.base, "backups"))
        self.assertFalse(result.ok)
        self.assertIn("outside", result.error)

    def test_tampered_archive_fails_verification(self):
        life_service.add_task(self.base, "Keep me")
        result = backup_service.create_backup(self.base, destination=self.dest)
        tampered = result.path + ".tampered.zip"
        with zipfile.ZipFile(result.path) as source, zipfile.ZipFile(tampered, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "tasks.json":
                    data = b"[]"
                target.writestr(info, data)
        checked = backup_service.verify_backup(tampered)
        self.assertFalse(checked["ok"])
        self.assertTrue(any("mismatch" in error for error in checked["errors"]), checked["errors"])

    def test_archive_traversal_is_rejected(self):
        path = _make_backup(
            os.path.join(self.dest, "evil.mei-backup.zip"),
            {"tasks.json": b"[]"},
            extra_paths={"../escape.txt": b"no"},
        )
        checked = backup_service.verify_backup(path)
        self.assertFalse(checked["ok"])
        self.assertTrue(any("unsafe" in error or "missing" in error or "not listed" in error for error in checked["errors"]))

    def test_incomplete_backup_is_not_verified(self):
        path = _make_backup(os.path.join(self.dest, "incomplete.mei-backup.zip"), {}, status="failed")
        checked = backup_service.verify_backup(path)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["status"], "incomplete")

    def test_retention_never_deletes_the_newest_verified_backup(self):
        now = 1_700_000_000
        made = []
        for index in range(5):
            result = backup_service.create_backup(
                self.base, destination=self.dest, now=now + index * 86400
            )
            self.assertTrue(result.ok, result.error)
            made.append(result.path)
        policy = backup_service.BackupPolicy(
            destination=self.dest, daily_keep=1, weekly_keep=1, monthly_keep=1
        )
        backup_service.apply_retention(self.dest, policy, now=now + 10 * 86400)
        self.assertTrue(os.path.exists(made[-1]))

    def test_conflict_archive_is_an_explicit_backup_category(self):
        task = life_service.add_task(self.base, "Local")
        conflict_service.record_conflict(
            self.base,
            store="tasks",
            record_id=task["id"],
            local=task,
            remote=dict(task, title="Remote"),
        )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        with zipfile.ZipFile(result.path) as archive:
            self.assertIn("Recovery/conflicts.json", archive.namelist())
            payload = json.loads(archive.read("Recovery/conflicts.json"))
        self.assertEqual(payload["conflicts"][0]["local"]["title"], "Local")
        self.assertEqual(payload["conflicts"][0]["remote"]["title"], "Remote")


class TestRestoreService(_Base):
    def _backup(self):
        life_service.add_task(self.base, "Original")
        personal_service.create_note(self.base, "Note", "original")
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        return result.path

    def test_restore_requires_confirmation_and_creates_pre_restore_backup(self):
        path = self._backup()
        life_service.save_tasks(self.base, [])
        with self.assertRaises(restore_service.RestoreError):
            restore_service.restore(self.base, path)
        result = restore_service.restore(self.base, path, confirm=True)
        self.assertTrue(result.ok, result.error)
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Original"])
        self.assertTrue(backup_service.verify_backup(result.pre_restore_backup)["ok"])
        self.assertEqual(result.status, "restored")

    def test_selective_restore_leaves_unselected_note_alone(self):
        path = self._backup()
        life_service.save_tasks(self.base, [])
        personal_service.save_note(self.base, "General/Note.md", "changed")
        result = restore_service.restore(self.base, path, categories=["tasks"], confirm=True)
        self.assertTrue(result.ok, result.error)
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Original"])
        self.assertEqual(personal_service.read_note(self.base, "General/Note.md")["content"], "changed")

    def test_failed_restore_rolls_back_the_original_bytes(self):
        path = self._backup()
        life_service.save_tasks(self.base, [{"id": "new", "title": "Local edit"}])
        real_journal = restore_service._journal

        def fail_commit(base_dir, data):
            if data.get("state") == "COMMITTED":
                raise OSError("simulated commit failure")
            return real_journal(base_dir, data)

        with mock.patch.object(restore_service, "_journal", side_effect=fail_commit):
            result = restore_service.restore(self.base, path, categories=["tasks"], confirm=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Local edit"])

    def test_future_schema_is_refused_without_touching_current_store(self):
        current = open(os.path.join(self.base, "prefs.json"), encoding="utf-8").read()
        path = _make_backup(
            os.path.join(self.dest, "future.mei-backup.zip"),
            {"prefs.json": json.dumps({"schema_version": 99, "x": 1}).encode()},
        )
        result = restore_service.restore(self.base, path, categories=["preferences"], confirm=True)
        self.assertFalse(result.ok)
        self.assertIn("newer schema", result.error)
        self.assertEqual(open(os.path.join(self.base, "prefs.json"), encoding="utf-8").read(), current)

    def test_restoring_a_conflict_backup_merges_and_never_activates(self):
        first = life_service.add_task(self.base, "First")
        conflict_service.record_conflict(
            self.base, store="tasks", record_id=first["id"], local=first, remote=dict(first, title="Remote first")
        )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        # Simulate the live archive losing the older conflict while a newer
        # conflict remains.  Restoring the backup must merge the old row back,
        # not replace the newer archive.
        os.remove(os.path.join(self.base, conflict_service.STORE_RELPATH))
        second = life_service.add_task(self.base, "Second")
        conflict_service.record_conflict(
            self.base, store="tasks", record_id=second["id"], local=second, remote=dict(second, title="Remote second")
        )
        restored = restore_service.restore(
            self.base, result.path, categories=["sync_conflicts"], confirm=True
        )
        self.assertTrue(restored.ok, restored.error)
        rows = conflict_service.list_conflicts(self.base)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == conflict_service.PENDING for row in rows))
        again = restore_service.restore(
            self.base, result.path, categories=["sync_conflicts"], confirm=True
        )
        self.assertFalse(again.ok)
        self.assertEqual(again.status, "unchanged")
        self.assertEqual(len(conflict_service.list_conflicts(self.base)), 2)
        self.assertEqual([task["title"] for task in life_service.load_tasks(self.base)], ["First", "Second"])


class TestIntegrityService(_Base):
    def test_scan_is_read_only_and_reports_healthy(self):
        life_service.add_task(self.base, "Fine")
        path = os.path.join(self.base, "tasks.json")
        before = os.stat(path).st_mtime_ns
        report = integrity_service.scan(self.base)
        self.assertEqual(report["summary"]["status"], "healthy")
        self.assertTrue(report["read_only"])
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_corrupt_store_is_critical_and_preserved(self):
        path = os.path.join(self.base, "tasks.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        report = integrity_service.scan(self.base)
        self.assertEqual(report["summary"]["by_severity"]["CRITICAL"], 1)
        self.assertEqual(open(path, encoding="utf-8").read(), "{broken")

    def test_duplicate_ids_and_orphan_planner_reference(self):
        life_service.save_tasks(
            self.base,
            [{"id": "same", "title": "A"}, {"id": "same", "title": "B"}],
        )
        self._write(
            "personal_plan.json",
            json.dumps(
                {
                    "version": 2,
                    "items": [{"id": "item", "title": "X", "course_id": "missing"}],
                    "courses": [],
                    "time_blocks": [],
                }
            ),
        )
        report = integrity_service.scan(self.base)
        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("duplicate_id", codes)
        self.assertIn("orphan_course_reference", codes)

    def test_cancellation_stops_the_scan(self):
        life_service.add_task(self.base, "Fine")
        report = integrity_service.scan(self.base, cancel=lambda: True)
        self.assertTrue(report["cancelled"])


class TestConflictService(_Base):
    def test_identical_conflicts_are_archived_once_and_resolved_auditable(self):
        task = life_service.add_task(self.base, "Local")
        remote = dict(task, title="Remote")
        first = conflict_service.record_conflict(
            self.base, store="tasks", record_id=task["id"], local=task, remote=remote
        )
        second = conflict_service.record_conflict(
            self.base, store="tasks", record_id=task["id"], local=task, remote=remote
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(conflict_service.status(self.base)["pending"], 1)
        denied = conflict_service.resolve_conflict(self.base, first["id"], "keep_remote")
        self.assertEqual(denied.status, "confirmation_required")
        result = conflict_service.resolve_conflict(
            self.base, first["id"], "keep_remote", confirm=True
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Remote"])
        self.assertEqual(conflict_service.status(self.base)["resolved"], 1)
        self.assertEqual(len(conflict_service.history(self.base)), 1)

    def test_keep_local_does_not_change_the_store(self):
        task = life_service.add_task(self.base, "Local")
        conflict = conflict_service.record_conflict(
            self.base, store="tasks", record_id=task["id"], local=task, remote=dict(task, title="Remote")
        )
        result = conflict_service.resolve_conflict(
            self.base, conflict["id"], "keep_local", confirm=True
        )
        self.assertTrue(result.ok)
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Local"])


class TestBackupScheduler(_Base):
    def test_daily_backup_runs_once_when_due(self):
        prefs.save_pref(
            self.base,
            "backup_policy",
            {
                "destination": self.dest,
                "enabled": True,
                "frequency": "daily",
                "scheduled_protection": "plaintext",
                "plaintext_acknowledged": True,
                "daily_keep": 7,
                "weekly_keep": 4,
                "monthly_keep": 6,
            },
        )
        scheduler = backup_scheduler.BackupScheduler(self.base, clock=lambda: 1_700_000_000)
        result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "created", result.error)
        self.assertTrue(os.path.isfile(result.path))
        again = scheduler.run_if_due(now=1_700_000_100)
        self.assertEqual(again.status, "not_due")
        self.assertEqual(scheduler.status(now=1_700_000_100)["last_status"], "not_due")

    def test_failure_keeps_previous_success_and_is_visible(self):
        prefs.save_pref(
            self.base,
            "backup_policy",
            {"destination": self.dest, "enabled": True, "frequency": "daily", "scheduled_protection": "plaintext", "plaintext_acknowledged": True},
        )
        scheduler = backup_scheduler.BackupScheduler(self.base)
        failed = backup_service.BackupResult(False, error="disk full")
        with mock.patch.object(backup_service, "create_backup", return_value=failed):
            result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "failed")
        status = scheduler.status(now=1_700_000_000)
        self.assertEqual(status["last_status"], "failed")
        self.assertIn("disk full", status["last_error"])
        self.assertEqual(status["last_success_at"], 0)

    def test_unfinished_restore_blocks_scheduling(self):
        prefs.save_pref(
            self.base,
            "backup_policy",
            {"destination": self.dest, "enabled": True, "frequency": "daily", "scheduled_protection": "plaintext", "plaintext_acknowledged": True},
        )
        write_json(
            restore_service.journal_path(self.base),
            {"state": "APPLYING", "files": []},
        )
        scheduler = backup_scheduler.BackupScheduler(self.base)
        result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "blocked_restore_review")


class TestRecordRestore(_Base):
    def test_deleted_task_can_be_previewed_and_restored_after_confirmation(self):
        task = life_service.add_task(self.base, "Recover me")
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        life_service.remove_task(self.base, task["id"])
        preview = record_restore_service.preview(self.base, result.path, "tasks", task["id"])
        self.assertTrue(preview["ok"])
        self.assertFalse(preview["exists"])
        with self.assertRaises(record_restore_service.RecordRestoreError):
            record_restore_service.restore(self.base, result.path, "tasks", task["id"])
        restored = record_restore_service.restore(
            self.base, result.path, "tasks", task["id"], confirm=True
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual([row["title"] for row in life_service.load_tasks(self.base)], ["Recover me"])
        self.assertTrue(os.path.isfile(restored["pre_restore_backup"]))

    def test_note_can_be_restored_as_a_new_file(self):
        note = personal_service.create_note(self.base, "Keep note", "original body")
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        personal_service.save_note(self.base, note["id"], "changed")
        preview = record_restore_service.preview(self.base, result.path, "notes", note["id"])
        self.assertTrue(preview["exists"])
        with self.assertRaises(record_restore_service.RecordRestoreError):
            record_restore_service.restore(self.base, result.path, "notes", note["id"])
        restored = record_restore_service.restore(
            self.base, result.path, "notes", note["id"], mode="as_new", confirm=True
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual(personal_service.read_note(self.base, note["id"])["content"], "changed")
        self.assertTrue(
            any("(restored)" in item["title"] for item in personal_service.list_notes(self.base))
        )

    def test_existing_record_requires_explicit_replace_confirmation(self):
        task = life_service.add_task(self.base, "Original")
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        life_service.save_tasks(self.base, [dict(task, title="Changed")])
        with self.assertRaises(record_restore_service.RecordRestoreError):
            record_restore_service.restore(self.base, result.path, "tasks", task["id"])
        restored = record_restore_service.restore(
            self.base, result.path, "tasks", task["id"], confirm=True
        )
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual(life_service.load_tasks(self.base)[0]["title"], "Original")


class TestRecoveryService(_Base):
    def test_session_marker_distinguishes_clean_shutdown(self):
        recovery_service.begin_session(self.base)
        self.assertTrue(recovery_service.inspect_startup(self.base)["unclean_previous_session"])
        recovery_service.end_session(self.base)
        self.assertFalse(recovery_service.inspect_startup(self.base)["unclean_previous_session"])

    def test_stale_temp_is_quarantined_then_removed(self):
        path = os.path.join(self.base, ".old-write.tmp")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("half written")
        old = time.time() - recovery_service.STALE_TEMP_SECONDS - 3600
        os.utime(path, (old, old))
        report = recovery_service.recover_startup(self.base)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(any(row.get("removed") for row in report["stale_temp_quarantine"]))
        self.assertEqual(storage_health.list_quarantine(self.base)[0]["category"], "stale_temp")

    def test_recovery_report_is_written(self):
        recovery_service.begin_session(self.base)
        recovery_service.recover_startup(self.base)
        self.assertTrue(os.path.isfile(recovery_service.report_path(self.base)))
        self.assertEqual(
            json.load(open(recovery_service.report_path(self.base), encoding="utf-8"))["kind"],
            "mei.startup_recovery",
        )


if __name__ == "__main__":
    unittest.main()
