"""Regressions for the critical data-safety and release-security fixes.

All profile, backup and fake-server work is isolated in temporary directories.
No real user profile, network endpoint, signing key or certificate is touched.
"""
import base64
import json
import os
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from litebrowser.core import prefs, storage_utils, update_keys
from litebrowser.core.storage_utils import CorruptionWriteError, read_json, write_json
from litebrowser.services import (
    backup_service,
    encrypted_backup_service,
    life_service,
    restore_service,
    sync_service,
    update_signature,
)
from tools import publish_release


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.dest = os.path.join(self._tmp.name, "backups")
        os.makedirs(self.dest, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()


class TestFailClosedQuarantine(_Base):
    def test_failed_preservation_never_overwrites_corrupt_bytes(self):
        path = os.path.join(self.base, "broken.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with mock.patch.object(
            storage_utils, "_preserve_corrupt_copy", side_effect=OSError("permission denied")
        ):
            with self.assertRaises(CorruptionWriteError):
                write_json(path, {"replacement": True})
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{broken")

    def test_read_failure_marks_store_write_blocked(self):
        path = os.path.join(self.base, "read-broken.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with mock.patch.object(
            storage_utils, "_preserve_corrupt_copy", side_effect=OSError("disk full")
        ):
            self.assertEqual(read_json(path, {}), {})
        with self.assertRaises(CorruptionWriteError):
            write_json(path, {"replacement": True})
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{broken")

    def test_verified_copy_is_byte_identical_and_blocks_replacement(self):
        path = os.path.join(self.base, "copy-broken.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(read_json(path, {}), {})
        with self.assertRaises(CorruptionWriteError):
            write_json(path, {"replacement": True})
        artifact = storage_utils.damaged_paths()[os.path.normcase(os.path.abspath(path))]
        with open(artifact, "rb") as handle:
            self.assertEqual(handle.read(), b"{broken")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"{broken")

    def test_changed_source_during_copy_is_not_treated_as_preserved(self):
        path = os.path.join(self.base, "changing-broken.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        real_stat = os.stat

        def changing_stat(target):
            result = real_stat(target)
            # The second stat is the source check after the copy. Report a
            # different size so the copy cannot be accepted as the source bytes.
            if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(path)):
                changing_stat.calls += 1
                if changing_stat.calls == 2:
                    return SimpleNamespace(
                        st_size=result.st_size + 1,
                        st_mtime_ns=result.st_mtime_ns,
                    )
            return result

        changing_stat.calls = 0
        with mock.patch.object(storage_utils.os, "stat", side_effect=changing_stat):
            with self.assertRaises(OSError):
                storage_utils._preserve_corrupt_copy(path)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{broken")
        self.assertFalse(any(".corrupt-" in name for name in os.listdir(self.base)))


class TestSyncArchiveGate(_Base):
    def _remote(self, task, title):
        return {
            "kind": "snapshot",
            "app": "litebrowser",
            "api": 1,
            "tasks": [dict(task, title=title, updated_at=task["updated_at"] + 10)],
        }

    def _fake_server(self, remote, calls):
        def request(url, token, method="GET", payload=None):
            calls.append(method)
            if method == "GET":
                return True, remote, ""
            return True, {}, ""

        return request

    def test_archive_failure_blocks_pull_push_and_baseline(self):
        task = life_service.add_task(self.base, "Local")
        calls = []
        remote = self._remote(task, "Remote")
        with mock.patch.object(sync_service, "_request", side_effect=self._fake_server(remote, calls)), \
             mock.patch.object(sync_service, "_archive_http_conflict", return_value=False):
            ok, message = sync_service.pull(self.base, "http://localhost:9", "token")
            self.assertFalse(ok)
            self.assertIn("preserve", message)
            self.assertEqual(calls, ["GET"])
            self.assertEqual(life_service.load_tasks(self.base)[0]["title"], "Local")
            self.assertEqual(life_service.load_sync_state(self.base).get("last_pull_at"), None)
            blocked, reason = sync_service.push(self.base, "http://localhost:9", "token")
            self.assertFalse(blocked)
            self.assertIn("blocked", reason.lower())
            self.assertEqual(calls, ["GET"])

    def test_archive_exception_has_the_same_gate(self):
        task = life_service.add_task(self.base, "Local")
        calls = []
        remote = self._remote(task, "Remote")
        with mock.patch.object(sync_service, "_request", side_effect=self._fake_server(remote, calls)), \
             mock.patch.object(sync_service, "_archive_http_conflict", side_effect=OSError("disk full")):
            ok, _message = sync_service.pull(self.base, "http://localhost:9", "token")
        self.assertFalse(ok)
        self.assertEqual(life_service.load_tasks(self.base)[0]["title"], "Local")
        self.assertTrue(life_service.load_sync_state(self.base).get("push_blocked"))

    def test_successful_retry_clears_gate(self):
        task = life_service.add_task(self.base, "Local")
        calls = []
        remote = self._remote(task, "Remote")
        with mock.patch.object(sync_service, "_request", side_effect=self._fake_server(remote, calls)), \
             mock.patch.object(sync_service, "_archive_http_conflict", return_value=False):
            self.assertFalse(sync_service.pull(self.base, "http://localhost:9", "token")[0])
        with mock.patch.object(sync_service, "_request", side_effect=self._fake_server(remote, calls)), \
             mock.patch.object(sync_service, "_archive_http_conflict", return_value=True):
            ok, _message = sync_service.pull(self.base, "http://localhost:9", "token")
        self.assertTrue(ok)
        self.assertFalse(life_service.load_sync_state(self.base).get("push_blocked"))
        self.assertEqual(life_service.load_tasks(self.base)[0]["title"], "Remote")

    def test_apply_result_exposes_archive_failure(self):
        task = life_service.add_task(self.base, "Local")
        remote = self._remote(task, "Remote")
        with mock.patch.object(sync_service, "_archive_http_conflict", return_value=False):
            result = sync_service._apply_bundle_result(self.base, remote)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "ARCHIVE_FAILED")
        self.assertEqual(result.failed_store, "tasks")


class TestRestoreSelectionAndJournal(_Base):
    def _backup(self):
        life_service.add_task(self.base, "Old")
        prefs.save_bookmarks(
            self.base, [{"title": "Old bookmark", "url": "https://example.test/one"}]
        )
        result = backup_service.create_backup(self.base, destination=self.dest)
        self.assertTrue(result.ok, result.error)
        return result

    def test_empty_selection_is_rejected_and_none_is_explicit_all(self):
        backup = self._backup()
        self.assertIsNone(restore_service._selected(None))
        for empty in ([], (), set()):
            with self.assertRaises(restore_service.RestoreError):
                restore_service._selected(empty)
        plan = restore_service.preview(self.base, backup.path, categories=[])
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["status"], "invalid_selection")
        before = open(os.path.join(self.base, "tasks.json"), "rb").read()
        result = restore_service.restore(
            self.base, backup.path, categories=[], confirm=True
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "invalid_selection")
        self.assertEqual(open(os.path.join(self.base, "tasks.json"), "rb").read(), before)

    def test_journal_records_hashes_and_rollback_artifacts(self):
        backup = self._backup()
        life_service.add_task(self.base, "Current")
        result = restore_service.restore(
            self.base, backup.path, categories=["tasks"], confirm=True
        )
        self.assertTrue(result.ok, result.error)
        with open(restore_service.journal_path(self.base), encoding="utf-8") as handle:
            journal = json.load(handle)
        self.assertEqual(journal["version"], restore_service.JOURNAL_VERSION)
        self.assertEqual(journal["state"], "COMMITTED")
        self.assertTrue(journal["pre_restore_backup"])
        row = next(row for row in journal["files"] if row["path"] == "tasks.json")
        self.assertEqual(len(row["staged_sha"]), 64)
        self.assertEqual(len(row["original_sha"]), 64)
        self.assertTrue(row["rollback"], "the journal names the rollback artifact")

    def test_crash_after_first_replacement_rolls_back_on_recovery(self):
        backup = self._backup()
        life_service.add_task(self.base, "Current")
        prefs.save_bookmarks(
            self.base, [{"title": "Current bookmark", "url": "https://example.test/one"}]
        )
        def canonical(path):
            return os.path.normcase(os.path.realpath(os.path.abspath(path)))

        tasks_path = canonical(os.path.join(self.base, "tasks.json"))
        bookmarks_path = canonical(os.path.join(self.base, "bookmarks.json"))
        real_write = restore_service._write_bytes_atomic
        hits = []

        def crash_after_first_target(path, data):
            real_write(path, data)
            if canonical(path) in {tasks_path, bookmarks_path}:
                hits.append(path)
                raise KeyboardInterrupt("simulated process termination")

        with mock.patch.object(restore_service, "_write_bytes_atomic", side_effect=crash_after_first_target):
            with self.assertRaises(KeyboardInterrupt):
                restore_service.restore(
                    self.base,
                    backup.path,
                    categories=["tasks", "bookmarks"],
                    confirm=True,
                )
        self.assertEqual(len(hits), 1, "the crash hook must intercept exactly one target")
        with open(restore_service.journal_path(self.base), encoding="utf-8") as handle:
            journal = json.load(handle)
        self.assertIn(journal["state"], {"APPLYING", "STAGED", "VERIFYING"})
        recovered = restore_service.recover_interrupted(self.base)
        self.assertEqual(recovered["status"], "rolled_back")
        self.assertIn("Current", {row["title"] for row in life_service.load_tasks(self.base)})
        self.assertEqual(prefs.load_bookmarks(self.base)[0]["title"], "Current bookmark")

    def test_encrypted_restore_uses_encrypted_pre_restore_backup(self):
        life_service.add_task(self.base, "Old")
        encrypted = encrypted_backup_service.create_encrypted_backup(
            self.base, "correct horse battery", destination=self.dest
        )
        self.assertTrue(encrypted.ok, encrypted.error)
        life_service.add_task(self.base, "Current")
        result = restore_service.restore(
            self.base,
            encrypted.path,
            categories=["tasks"],
            confirm=True,
            password="correct horse battery",
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.pre_restore_protection, "encrypted")
        self.assertTrue(result.pre_restore_backup.endswith(".mei-backup.enc"))
        self.assertTrue(os.path.isfile(result.pre_restore_backup))


class TestEncryptedHeaderAndTemp(_Base):
    def _encrypted(self):
        life_service.add_task(self.base, "encrypted payload")
        result = encrypted_backup_service.create_encrypted_backup(
            self.base, "correct horse battery", destination=self.dest
        )
        self.assertTrue(result.ok, result.error)
        return result.path

    def _rewrite_header(self, path, mutate):
        raw = open(path, "rb").read()
        magic = encrypted_backup_service.MAGIC
        length = struct.unpack(">I", raw[len(magic):len(magic) + 4])[0]
        start = len(magic) + 4
        header = json.loads(raw[start:start + length].decode("utf-8"))
        mutate(header)
        changed = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
        out = magic + struct.pack(">I", len(changed)) + changed + raw[start + length:]
        target = path + ".header"
        with open(target, "wb") as handle:
            handle.write(out)
        return target

    def test_hostile_kdf_is_rejected_before_derivation(self):
        path = self._encrypted()

        def expensive(header):
            header["n"] = 2**18

        hostile = self._rewrite_header(path, expensive)
        with mock.patch.object(encrypted_backup_service, "Scrypt") as scrypt:
            checked = encrypted_backup_service.inspect(hostile)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["status"], "invalid_kdf")
        scrypt.assert_not_called()

    def test_non_integer_header_is_rejected(self):
        path = self._encrypted()
        hostile = self._rewrite_header(path, lambda header: header.__setitem__("n", "32768"))
        checked = encrypted_backup_service.inspect(hostile)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["status"], "invalid_header")

    def _owner(self, path, pid):
        manifest = {
            "kind": "mei.temp_operation",
            "version": 1,
            "operation_id": os.path.basename(path)[3:],
            "operation": "decrypt",
            "pid": pid,
            "process_start": "",
            "created_at": 1,
            "lease_until": 1,
        }
        with open(os.path.join(path, "owner.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)

    def test_stale_private_temp_is_cleaned_without_touching_unrelated_files(self):
        def canonical(path):
            return os.path.normcase(os.path.realpath(os.path.abspath(path)))

        with tempfile.TemporaryDirectory() as tmp:
            env = {encrypted_backup_service.TEMP_ROOT_ENV: tmp}
            with mock.patch.dict(os.environ, env):
                root = os.path.join(tmp, encrypted_backup_service.PRIVATE_TEMP_DIR_NAME)
                os.makedirs(root)
                stale = os.path.join(root, "op-" + "a" * 32)
                fresh = os.path.join(root, "op-" + "b" * 32)
                unrelated_dir = os.path.join(root, "not-an-operation")
                unrelated = os.path.join(tmp, "unrelated.txt")
                os.makedirs(stale)
                os.makedirs(fresh)
                os.makedirs(unrelated_dir)
                self._owner(stale, 99999999)
                self._owner(fresh, os.getpid())
                with open(unrelated, "wb") as handle:
                    handle.write(b"unrelated")
                os.utime(stale, (1, 1))
                os.utime(fresh, (1, 1))
                os.utime(unrelated_dir, (1, 1))
                removed = encrypted_backup_service.cleanup_stale_temp(now=2**31 - 1)
            self.assertEqual([canonical(path) for path in removed], [canonical(stale)])
            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.exists(fresh), "a live operation is never removed")
            self.assertTrue(os.path.exists(unrelated))
            self.assertTrue(os.path.exists(unrelated_dir))


class TestReleasePreflight(_Base):
    def _exe(self):
        path = os.path.join(self._tmp.name, "Mei.exe")
        with open(path, "wb") as handle:
            handle.write(b"MZ" + b"\0" * 2000)
        return path

    def test_stable_signing_requires_both_key_parts(self):
        exe = self._exe()
        with mock.patch.dict(os.environ, {"MEI_UPDATE_KEY_ID": "release-2026"}, clear=False):
            os.environ.pop("MEI_UPDATE_SIGNING_KEY", None)
            with self.assertRaises(ValueError):
                publish_release.build_manifest(
                    version="1.0.1.0",
                    exe_path=exe,
                    download_url="https://h/Mei.exe",
                    require_signature=True,
                )

    def test_missing_signing_key_blocks_before_upload(self):
        exe = self._exe()
        with mock.patch.dict(
            os.environ,
            {"MEI_UPDATE_KEY_ID": "", "MEI_UPDATE_SIGNING_KEY": ""},
            clear=False,
        ), mock.patch.object(publish_release, "_ensure_release") as ensure, \
           mock.patch.object(publish_release, "_upload_asset") as upload:
            with self.assertRaises(ValueError):
                publish_release.publish(
                    tag="v1.0.1.0",
                    repo="example/Mei",
                    exe=exe,
                    web_support="",
                    notes="",
                    token="token",
                    out_dir=self._tmp.name,
                )
        ensure.assert_not_called()
        upload.assert_not_called()

    def test_signed_manifest_is_verified_against_pinned_key(self):
        exe = self._exe()
        private = Ed25519PrivateKey.generate()
        public = update_signature.public_key_b64(private)
        with mock.patch.dict(
            os.environ,
            {
                "MEI_UPDATE_KEY_ID": "release-2026",
                "MEI_UPDATE_SIGNING_KEY": base64.b64encode(
                    private.private_bytes_raw()
                ).decode("ascii"),
            },
            clear=False,
        ), mock.patch.object(update_keys, "TRUSTED_UPDATE_KEYS", {"release-2026": public}):
            manifest = publish_release.build_manifest(
                version="1.0.1.0",
                exe_path=exe,
                download_url="https://h/Mei.exe",
                require_signature=True,
            )
        self.assertEqual(manifest["key_id"], "release-2026")
        self.assertTrue(manifest["signature"])

    def test_workflow_has_no_control_characters_and_signs_through_a_cloud_provider(self):
        """A backtick-eaten ``\\b`` once shipped a control character into this YAML.

        The signing step no longer shells out to signtool with a PFX: since the
        2026 CA/B rules a code-signing key must live in FIPS hardware and no CA
        issues exportable .pfx files any more. What is pinned here is that the
        file stays control-character free and that signing goes through the
        cloud-HSM action gated by a *variable* — a `secrets` expression in a step
        `if:` is not evaluated by GitHub, which is how the old step silently
        never ran even when a PFX was configured.
        """
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows", "release.yml")
        raw = open(path, "rb").read()
        self.assertNotIn(b"\x08", raw)
        self.assertFalse(
            any(byte < 0x09 for byte in raw),
            "a control character means a backtick escape was eaten",
        )
        text = raw.decode("utf-8")
        self.assertIn("azure/trusted-signing-action", text)
        self.assertIn("vars.MEI_SIGNING_PROVIDER", text)
        self.assertNotIn("secrets.MEI_SIGNING_PFX_BASE64", text)


if __name__ == "__main__":
    unittest.main()
