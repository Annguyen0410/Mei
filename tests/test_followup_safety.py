"""Follow-up regressions for rollback integrity and fail-closed sync.

Every profile, backup and fake endpoint lives in a temporary directory.  The
crash hook proves it actually intercepted a live target write; a test that
never reaches the hook cannot pass.
"""
import base64
import json
import os
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from litebrowser.core import prefs, product, storage_health, update_keys
from litebrowser.core.storage_health import JsonReadResult
from litebrowser.services import (
    backup_scheduler,
    backup_service,
    encrypted_backup_service,
    life_service,
    restore_service,
    sync_service,
)
from tools import publish_release


def canonical(path: str) -> str:
    """One identity for a path, independent of short/long Windows aliases."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.dest = os.path.join(self._tmp.name, "backups")
        os.makedirs(self.dest, exist_ok=True)
        sync_service._clear_fail_closed(self.base)

    def tearDown(self):
        sync_service._clear_fail_closed(self.base)
        self._tmp.cleanup()

    def journal(self) -> dict:
        with open(restore_service.journal_path(self.base), encoding="utf-8") as handle:
            return json.load(handle)

    def sync_journal(self) -> dict:
        with open(sync_service.sync_journal_path(self.base), encoding="utf-8") as handle:
            return json.load(handle)

    def backup(self, with_bookmarks: bool = False):
        life_service.add_task(self.base, "Original task")
        if with_bookmarks:
            prefs.save_bookmarks(
                self.base,
                [{"title": "Original bookmark", "url": "https://example.test/one"}],
            )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        # Make the live profile differ from the archive so the restore has work.
        life_service.add_task(self.base, "Current task")
        if with_bookmarks:
            prefs.save_bookmarks(
                self.base,
                [{"title": "Current bookmark", "url": "https://example.test/one"}],
            )
        return result

    def interrupt_before_restore(self, backup, categories):
        """Crash before the first live target is replaced."""
        targets = {
            canonical(os.path.join(self.base, f"{name}.json")) for name in categories
        }
        seen = {"targets": 0}
        real_write = restore_service._write_bytes_atomic

        def hook(path, data):
            if canonical(path) in targets:
                seen["targets"] += 1
                raise KeyboardInterrupt("simulated crash before apply")
            real_write(path, data)

        with mock.patch.object(
            restore_service, "_write_bytes_atomic", side_effect=hook
        ):
            with self.assertRaises(KeyboardInterrupt):
                restore_service.restore(
                    self.base, backup.path, categories=categories, confirm=True
                )
        self.assertEqual(seen["targets"], 1)
        return seen

    def interrupt_restore(self, backup, categories, *, after: int = 1):
        """Crash once the expected number of live target writes completed."""
        targets = {
            canonical(os.path.join(self.base, f"{name}.json")) for name in categories
        }
        seen = {"targets": 0}
        real_write = restore_service._write_bytes_atomic

        def hook(path, data):
            real_write(path, data)
            if canonical(path) in targets:
                seen["targets"] += 1
                if seen["targets"] >= after:
                    raise KeyboardInterrupt("simulated process termination")

        with mock.patch.object(
            restore_service, "_write_bytes_atomic", side_effect=hook
        ):
            with self.assertRaises(KeyboardInterrupt):
                restore_service.restore(
                    self.base,
                    backup.path,
                    categories=categories,
                    confirm=True,
                )
        self.assertEqual(
            seen["targets"],
            after,
            "the crash hook must intercept exactly the intended target writes",
        )
        return seen


class TestRestoreRollbackClassification(_Base):
    def test_untouched_original_is_not_rewritten(self):
        backup = self.backup()
        before = read_bytes(os.path.join(self.base, "tasks.json"))
        self.interrupt_before_restore(backup, ["tasks"])
        journal = self.journal()
        self.assertEqual(journal["state"], "APPLYING")
        self.assertEqual(read_bytes(os.path.join(self.base, "tasks.json")), before)
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertEqual(read_bytes(os.path.join(self.base, "tasks.json")), before)
        self.assertEqual(self.journal()["state"], "ROLLED_BACK")

    def test_staged_target_rolls_back_to_verified_original(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        original_sha = self.journal()["files"][0]["original_sha"]
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertEqual(
            storage_health.file_sha256(os.path.join(self.base, "tasks.json")),
            original_sha,
        )
        self.assertEqual(self.journal()["state"], "ROLLED_BACK")

    def test_missing_target_is_restored_from_verified_rollback(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        original_sha = self.journal()["files"][0]["original_sha"]
        os.remove(os.path.join(self.base, "tasks.json"))
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertEqual(
            storage_health.file_sha256(os.path.join(self.base, "tasks.json")),
            original_sha,
        )

    def test_unknown_live_content_is_never_overwritten(self):
        """The critical case: original A, staged B, independent live C."""
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        independent = b'[{"id": "independent", "title": "Written after crash"}]'
        tasks_path = os.path.join(self.base, "tasks.json")
        with open(tasks_path, "wb") as handle:
            handle.write(independent)
        journal = self.journal()
        rollback = os.path.join(
            self.base,
            restore_service.STAGING_RELPATH,
            journal["operation_id"],
            journal["files"][0]["rollback"].replace("/", os.sep),
        )
        staged = os.path.join(
            self.base,
            restore_service.STAGING_RELPATH,
            journal["operation_id"],
            journal["files"][0]["staged"].replace("/", os.sep),
        )
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertEqual(
            read_bytes(tasks_path),
            independent,
            "an unknown target must remain byte-for-byte intact",
        )
        self.assertEqual(self.journal()["state"], "RECOVERY_REQUIRED")
        self.assertTrue(os.path.isfile(rollback), "the original artifact is preserved")
        self.assertTrue(os.path.isfile(staged), "the staged artifact is preserved")

    def test_unreadable_target_is_never_treated_as_missing(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        tasks_path = os.path.join(self.base, "tasks.json")
        os.remove(tasks_path)
        os.makedirs(tasks_path)
        try:
            recovered = restore_service.recover_interrupted(self.base)
            self.assertEqual(recovered["status"], "recovery_required")
            self.assertTrue(os.path.isdir(tasks_path))
            self.assertEqual(self.journal()["state"], "RECOVERY_REQUIRED")
        finally:
            os.rmdir(tasks_path)

    def test_corrupt_rollback_copy_preserves_the_staged_target(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        journal = self.journal()
        rollback = os.path.join(
            self.base,
            restore_service.STAGING_RELPATH,
            journal["operation_id"],
            journal["files"][0]["rollback"].replace("/", os.sep),
        )
        with open(rollback, "wb") as handle:
            handle.write(b"corrupt")
        before = read_bytes(os.path.join(self.base, "tasks.json"))
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertIn("corrupt", recovered["detail"])
        self.assertEqual(read_bytes(os.path.join(self.base, "tasks.json")), before)

    def test_missing_rollback_copy_preserves_the_target(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        journal = self.journal()
        rollback = os.path.join(
            self.base,
            restore_service.STAGING_RELPATH,
            journal["operation_id"],
            journal["files"][0]["rollback"].replace("/", os.sep),
        )
        os.remove(rollback)
        before = read_bytes(os.path.join(self.base, "tasks.json"))
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertEqual(read_bytes(os.path.join(self.base, "tasks.json")), before)

    def test_mixed_states_roll_back_the_safe_target_and_keep_the_unknown_one(self):
        backup = self.backup(with_bookmarks=True)
        self.interrupt_restore(backup, ["tasks", "bookmarks"], after=2)
        independent = b'[{"id": "later", "title": "Later bookmark", "url": "https://example.test/later"}]'
        bookmarks_path = os.path.join(self.base, "bookmarks.json")
        with open(bookmarks_path, "wb") as handle:
            handle.write(independent)
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "recovery_required")
        self.assertEqual(read_bytes(bookmarks_path), independent)
        titles = {row.get("title") for row in life_service.load_tasks(self.base)}
        self.assertIn("Original task", titles)
        self.assertIn("Current task", titles)

    def test_crash_during_rollback_recovers_on_the_next_startup(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        with mock.patch.object(
            restore_service, "_write_bytes_atomic", side_effect=OSError("disk full")
        ):
            first = restore_service.recover_interrupted(self.base)
        self.assertEqual(first["status"], "recovery_required")
        second = restore_service.recover_interrupted(self.base)
        self.assertEqual(second["status"], "rolled_back")
        self.assertIn(
            "Original task", {row.get("title") for row in life_service.load_tasks(self.base)}
        )

    def test_repeated_recovery_is_idempotent(self):
        backup = self.backup()
        self.interrupt_restore(backup, ["tasks"], after=1)
        first = restore_service.recover_interrupted(self.base)
        before = read_bytes(os.path.join(self.base, "tasks.json"))
        second = restore_service.recover_interrupted(self.base)
        self.assertEqual(first["status"], "rolled_back")
        self.assertEqual(second["status"], "rolled_back")
        self.assertEqual(read_bytes(os.path.join(self.base, "tasks.json")), before)


class TestCheckedSyncState(_Base):
    def state_path(self):
        return life_service.sync_state_path(self.base)

    def test_missing_state_is_healthy_and_push_is_allowed(self):
        checked = life_service.load_sync_state_checked(self.base)
        self.assertEqual(checked.status, life_service.SYNC_STATE_MISSING)
        self.assertTrue(checked.ok)
        with mock.patch.object(sync_service, "_request", return_value=(True, {}, "")):
            self.assertTrue(sync_service.push(self.base, "http://localhost:9", "token")[0])

    def test_corrupt_state_blocks_push_before_any_request(self):
        with open(self.state_path(), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        checked = life_service.load_sync_state_checked(self.base)
        self.assertEqual(checked.status, life_service.SYNC_STATE_CORRUPT)
        with mock.patch.object(sync_service, "_request") as request:
            ok, reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        self.assertIn("blocked", reason.lower())
        request.assert_not_called()

    def test_unreadable_state_blocks_push_before_any_request(self):
        state = canonical(self.state_path())
        real = storage_health.read_json_checked

        def checked(path, *args, **kwargs):
            if canonical(path) == state:
                return JsonReadResult(path=path, status="unreadable", detail="access denied")
            return real(path, *args, **kwargs)

        with mock.patch.object(
            sync_service.storage_health, "read_json_checked", side_effect=checked
        ), mock.patch.object(sync_service, "_request") as request:
            ok, reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        self.assertIn("unreadable", reason.lower())
        request.assert_not_called()

    def test_invalid_schema_blocks_push(self):
        with open(self.state_path(), "w", encoding="utf-8") as handle:
            json.dump({"push_blocked": "yes"}, handle)
        checked = life_service.load_sync_state_checked(self.base)
        self.assertEqual(checked.status, life_service.SYNC_STATE_INVALID_SCHEMA)
        with mock.patch.object(sync_service, "_request") as request:
            ok, _reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        request.assert_not_called()

    def test_empty_state_is_not_treated_as_a_clean_first_run(self):
        open(self.state_path(), "wb").close()
        checked = life_service.load_sync_state_checked(self.base)
        self.assertEqual(checked.status, life_service.SYNC_STATE_EMPTY)
        self.assertFalse(checked.ok)


class TestSyncSafetyJournal(_Base):
    def remote(self, title="Remote", updated=200):
        return {
            "kind": "snapshot",
            "app": "litebrowser",
            "api": 1,
            "tasks": [
                {
                    "id": "task-1",
                    "title": title,
                    "updated_at": updated,
                    "created_at": 1,
                }
            ],
        }

    def request(self, calls, remote=None, error=None):
        snapshot = remote if remote is not None else self.remote()

        def fake(url, token, method="GET", payload=None):
            calls.append(method)
            if method == "GET":
                if error is not None:
                    return False, None, error
                return True, snapshot, ""
            return True, {}, ""

        return fake

    def test_corrupt_journal_blocks_both_push_and_pull(self):
        os.makedirs(os.path.dirname(sync_service.sync_journal_path(self.base)), exist_ok=True)
        with open(sync_service.sync_journal_path(self.base), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with mock.patch.object(sync_service, "_request") as request:
            ok, reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        self.assertIn("journal", reason.lower())
        request.assert_not_called()
        result = sync_service.pull_typed(self.base, "http://localhost:9", "token")
        self.assertEqual(result.status, sync_service.PULL_RECOVERY_REQUIRED)

    def test_journal_write_failure_fails_closed(self):
        with mock.patch.object(sync_service, "_write_sync_journal", return_value=False):
            result = sync_service.pull_typed(self.base, "http://localhost:9", "token")
        self.assertEqual(result.status, sync_service.PULL_JOURNAL_FAILED)
        self.assertTrue(sync_service._is_fail_closed(self.base))
        with mock.patch.object(sync_service, "_request") as request:
            ok, _reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        request.assert_not_called()

    def test_no_remote_snapshot_permits_only_the_initial_push(self):
        calls = []
        fake = self.request(calls, error=sync_service._NO_REMOTE_SNAPSHOT)
        with mock.patch.object(sync_service, "_request", side_effect=fake):
            ok, _message = sync_service.sync_now(
                self.base, "http://localhost:9", "token"
            )
        self.assertTrue(ok)
        self.assertEqual(calls, ["GET", "POST"])
        self.assertEqual(self.sync_journal()["state"], sync_service.JOURNAL_CLEAN)

    def test_network_error_does_not_authorise_a_push(self):
        calls = []
        fake = self.request(calls, error="connection refused")
        with mock.patch.object(sync_service, "_request", side_effect=fake):
            ok, _message = sync_service.sync_now(
                self.base, "http://localhost:9", "token"
            )
        self.assertFalse(ok)
        self.assertEqual(calls, ["GET"])

    def test_error_text_that_looks_like_no_snapshot_does_not_authorise_push(self):
        calls = []
        fake = self.request(calls, error="No snapshot yet")
        with mock.patch.object(sync_service, "_request", side_effect=fake):
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
            ok, _message = sync_service.sync_now(
                self.base, "http://localhost:9", "token"
            )
        self.assertEqual(result.status, sync_service.PULL_NETWORK_ERROR)
        self.assertFalse(ok)
        self.assertEqual(calls, ["GET", "GET"])

    def test_journal_is_applying_before_the_merge_starts(self):
        seen = {}
        bundle = self.remote()
        real_result = sync_service.BundleMergeResult

        def probe(base_dir, incoming):
            with open(
                sync_service.sync_journal_path(base_dir), encoding="utf-8"
            ) as handle:
                seen["state"] = json.load(handle)["state"]
            return real_result({"tasks": 0}, "UNCHANGED")

        calls = []
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request(calls, remote=bundle)
        ), mock.patch.object(sync_service, "_apply_bundle_result", side_effect=probe):
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(seen["state"], sync_service.JOURNAL_APPLYING)

    def test_archive_failure_blocks_push_and_preserves_the_staged_bundle(self):
        local = life_service.add_task(self.base, "Local")
        local["updated_at"] = 100
        life_service.save_tasks(self.base, [local])
        remote = {
            "kind": "snapshot",
            "app": "litebrowser",
            "api": 1,
            "tasks": [dict(local, title="Remote", updated_at=200)],
        }
        calls = []
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request(calls, remote=remote)
        ), mock.patch.object(
            sync_service, "_archive_http_conflict", return_value=False
        ):
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
        self.assertEqual(result.status, sync_service.PULL_ARCHIVE_FAILED)
        journal = self.sync_journal()
        self.assertEqual(journal["state"], sync_service.JOURNAL_ARCHIVE_PENDING)
        self.assertTrue(os.path.isfile(os.path.join(self.base, journal["bundle_path"])))
        with mock.patch.object(sync_service, "_request") as request:
            blocked, reason = sync_service.push(
                self.base, "http://localhost:9", "token"
            )
        self.assertFalse(blocked)
        self.assertIn("blocked", reason.lower())
        request.assert_not_called()

    def test_successful_retry_keeps_previous_evidence_and_clears_the_gate(self):
        local = life_service.add_task(self.base, "Local")
        local["updated_at"] = 100
        life_service.save_tasks(self.base, [local])
        remote = {
            "kind": "snapshot",
            "app": "litebrowser",
            "api": 1,
            "tasks": [dict(local, title="Remote", updated_at=200)],
        }
        calls = []
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request(calls, remote=remote)
        ), mock.patch.object(
            sync_service, "_archive_http_conflict", return_value=False
        ):
            self.assertFalse(
                sync_service.pull_typed(
                    self.base, "http://localhost:9", "token"
                ).ok
            )
        prior_bundle = self.sync_journal()["bundle_path"]
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request(calls, remote=remote)
        ), mock.patch.object(
            sync_service, "_archive_http_conflict", return_value=True
        ):
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
        self.assertTrue(result.ok, result.message)
        journal = self.sync_journal()
        self.assertEqual(journal["state"], sync_service.JOURNAL_BASELINE_COMMITTED)
        self.assertEqual(
            journal["previous"]["state"], sync_service.JOURNAL_ARCHIVE_PENDING
        )
        self.assertFalse(life_service.load_sync_state(self.base).get("push_blocked"))
        self.assertFalse(os.path.exists(os.path.join(self.base, journal["bundle_path"])))
        self.assertTrue(
            os.path.exists(os.path.join(self.base, prior_bundle)),
            "the failed operation's staged snapshot is preserved as evidence",
        )

    def test_baseline_failure_keeps_push_blocked_after_data_was_applied(self):
        calls = []
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request(calls)
        ), mock.patch.object(
            sync_service, "_record_sync", side_effect=OSError("disk full")
        ):
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
        self.assertEqual(result.status, sync_service.PULL_BASELINE_FAILED)
        self.assertEqual(self.sync_journal()["state"], sync_service.JOURNAL_APPLIED)
        self.assertIn(
            "Remote", {row.get("title") for row in life_service.load_tasks(self.base)}
        )
        with mock.patch.object(sync_service, "_request") as request:
            ok, _reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        request.assert_not_called()

    def test_staging_failure_aborts_before_any_merge(self):
        with mock.patch.object(
            sync_service, "_request", side_effect=self.request([])
        ), mock.patch.object(
            sync_service, "_stage_bundle", return_value=False
        ), mock.patch.object(sync_service, "_apply_bundle_result") as apply:
            result = sync_service.pull_typed(
                self.base, "http://localhost:9", "token"
            )
        self.assertEqual(result.status, sync_service.PULL_JOURNAL_FAILED)
        apply.assert_not_called()
        self.assertTrue(sync_service._is_fail_closed(self.base))

    def test_push_block_state_write_failure_is_still_blocked_by_the_journal(self):
        with open(life_service.sync_state_path(self.base), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertFalse(sync_service._block_push(self.base, "archive failed"))
        journal = self.sync_journal()
        self.assertFalse(journal["block_metadata"]["sync_state"])
        self.assertTrue(journal["block_metadata"]["journal"])
        with mock.patch.object(sync_service, "_request") as request:
            ok, _reason = sync_service.push(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        request.assert_not_called()


class TestRestorePathIdentity(unittest.TestCase):
    def test_short_and_long_aliases_share_one_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tasks.json")
            open(path, "wb").close()
            self.assertEqual(canonical(path), canonical(os.path.join(tmp, ".", "tasks.json")))
            second = os.path.join(tmp, "tasks-link.json")
            try:
                os.link(path, second)
            except OSError:
                self.skipTest("hard links are not available on this filesystem")
            self.assertTrue(os.path.samefile(path, second))
            # Hard links share bytes but not a path identity; canonical() must
            # stay a path normaliser, while samefile() answers object identity.
            self.assertTrue(os.path.samefile(path, second))


class TestScheduledProtection(_Base):
    def policy(self, **overrides):
        value = {
            "destination": self.dest,
            "enabled": True,
            "frequency": "daily",
            "scheduled_protection": "plaintext",
            "plaintext_acknowledged": True,
        }
        value.update(overrides)
        prefs.save_pref(self.base, "backup_policy", value)

    def test_plaintext_requires_explicit_acknowledgement(self):
        self.policy(plaintext_acknowledged=False)
        scheduler = backup_scheduler.BackupScheduler(self.base)
        result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "blocked_plaintext_not_acknowledged")
        self.assertIn("plaintext", result.error.lower())
        self.assertEqual(os.listdir(self.dest), [])
        status = scheduler.status(now=1_700_000_000)
        self.assertFalse(status["protection"]["ok"])
        self.assertFalse(status["protection"]["explicit"])

    def test_requested_encryption_is_blocked_not_downgraded(self):
        self.policy(scheduled_protection="encrypted", plaintext_acknowledged=True)
        scheduler = backup_scheduler.BackupScheduler(self.base)
        result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "blocked_machine_bound_encryption_unavailable")
        self.assertEqual(os.listdir(self.dest), [])
        self.assertIn("not available", result.error.lower())

    def test_acknowledged_plaintext_scheduled_backup_is_created(self):
        self.policy()
        scheduler = backup_scheduler.BackupScheduler(self.base)
        result = scheduler.run_if_due(now=1_700_000_000)
        self.assertEqual(result.status, "created", result.error)
        self.assertTrue(os.path.isfile(result.path))
        self.assertIn("plaintext", scheduler.status(now=1_700_000_000)["protection"]["warning"].lower())


class TestTempOperationOwnership(_Base):
    def test_operation_directory_records_its_owner_before_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {encrypted_backup_service.TEMP_ROOT_ENV: tmp}
            ):
                path, owner = encrypted_backup_service._operation_dir("decrypt")
                self.assertTrue(os.path.isfile(os.path.join(path, "owner.json")))
                self.assertEqual(owner["pid"], os.getpid())
                self.assertEqual(owner["operation"], "decrypt")
                self.assertTrue(
                    os.path.realpath(path).startswith(
                        os.path.realpath(os.path.join(tmp, "MeiSecureTemp"))
                    )
                )
                encrypted_backup_service._release_operation(path)

    def test_live_operation_older_than_a_day_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {encrypted_backup_service.TEMP_ROOT_ENV: tmp}
            ):
                path, _owner = encrypted_backup_service._operation_dir("decrypt")
                os.utime(path, (1, 1))
                removed = encrypted_backup_service.cleanup_stale_temp(now=2**31 - 1)
                self.assertEqual(removed, [])
                self.assertTrue(os.path.isdir(path))
                encrypted_backup_service._release_operation(path)

    def test_wrong_password_leaves_no_plaintext_operation_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {encrypted_backup_service.TEMP_ROOT_ENV: tmp}
            ):
                life_service.add_task(self.base, "Encrypted payload")
                result = encrypted_backup_service.create_encrypted_backup(
                    self.base, "correct horse battery", destination=self.dest
                )
                self.assertTrue(result.ok, result.error)
                checked = encrypted_backup_service.verify_encrypted(
                    result.path, "wrong password!!"
                )
                self.assertFalse(checked["ok"])
                root = os.path.join(tmp, "MeiSecureTemp")
                self.assertEqual(
                    [name for name in os.listdir(root) if name.startswith("op-")],
                    [],
                )

    def test_materialized_plaintext_is_released_after_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {encrypted_backup_service.TEMP_ROOT_ENV: tmp}
            ):
                life_service.add_task(self.base, "Encrypted payload")
                result = encrypted_backup_service.create_encrypted_backup(
                    self.base, "correct horse battery", destination=self.dest
                )
                self.assertTrue(result.ok, result.error)
                with encrypted_backup_service.materialized(
                    result.path, "correct horse battery"
                ) as plain:
                    self.assertTrue(os.path.isfile(plain))
                self.assertFalse(os.path.exists(plain))
                root = os.path.join(tmp, "MeiSecureTemp")
                self.assertEqual(
                    [name for name in os.listdir(root) if name.startswith("op-")],
                    [],
                )


class TestReleaseUploadGates(_Base):
    def _exe(self):
        path = os.path.join(self._tmp.name, "Mei.exe")
        with open(path, "wb") as handle:
            handle.write(b"MZ" + b"\0" * 2000)
        return path

    def _signing_env(self):
        private = Ed25519PrivateKey.generate()
        return {
            "MEI_UPDATE_KEY_ID": "release-2026",
            "MEI_UPDATE_SIGNING_KEY": base64.b64encode(
                private.private_bytes_raw()
            ).decode("ascii"),
        }

    def test_unpinned_public_key_blocks_stable_manifest(self):
        exe = self._exe()
        with mock.patch.dict(os.environ, self._signing_env(), clear=False), \
             mock.patch.object(update_keys, "TRUSTED_UPDATE_KEYS", {}), \
             mock.patch.object(update_keys, "trusted_keys", return_value={}):
            with self.assertRaises(ValueError):
                publish_release.build_manifest(
                    version="1.0.1.0",
                    exe_path=exe,
                    download_url="https://h/Mei.exe",
                    require_signature=True,
                )

    def test_signature_verification_failure_uploads_nothing(self):
        exe = self._exe()
        with mock.patch.dict(os.environ, self._signing_env(), clear=False), \
             mock.patch.object(update_keys, "TRUSTED_UPDATE_KEYS", {}), \
             mock.patch.object(update_keys, "trusted_keys", return_value={}), \
             mock.patch.object(
                 publish_release,
                 "verify_build",
                 return_value={"size": os.path.getsize(exe), "sha256": "0" * 64},
             ), \
             mock.patch.object(publish_release, "build_release_body", return_value=""), \
             mock.patch.object(publish_release, "_ensure_release") as ensure, \
             mock.patch.object(publish_release, "_upload_asset") as upload:
            with self.assertRaises(ValueError):
                publish_release.publish(
                    tag="v" + product.APP_VERSION,
                    repo="example/Mei",
                    exe=exe,
                    web_support="",
                    notes="",
                    token="token",
                    out_dir=self._tmp.name,
                )
        ensure.assert_not_called()
        upload.assert_not_called()

    def test_stable_workflow_requires_authenticode_and_signing_key(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".github",
            "workflows",
            "release.yml",
        )
        raw = open(path, "rb").read()
        self.assertIn(b"Require Authenticode for stable release", raw)
        self.assertIn(b"Get-AuthenticodeSignature", raw)
        self.assertIn(b"MEI_UPDATE_SIGNING_KEY", raw)
        self.assertNotIn(b"\x08", raw)


if __name__ == "__main__":
    unittest.main()
