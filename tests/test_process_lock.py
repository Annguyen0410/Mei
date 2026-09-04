"""Cross-process profile lock: claim, conflict, release."""
import os
import tempfile
import unittest

from litebrowser.core import profile_lock, prefs


class TestProcessLock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))

    def tearDown(self):
        profile_lock.release_process_lock(self.base)
        self._tmp.cleanup()

    def test_acquire_and_conflict(self):
        acquired, _ = profile_lock.try_acquire_process_lock(self.base)
        self.assertTrue(acquired)
        # Same process re-acquire is a no-op success (already ours).
        again, _ = profile_lock.try_acquire_process_lock(self.base)
        self.assertTrue(again)

    def test_lock_file_created(self):
        profile_lock.try_acquire_process_lock(self.base)
        self.assertTrue(os.path.isfile(os.path.join(self.base, ".mei-profile-lock")))

    def test_release_allows_reacquire(self):
        self.assertTrue(profile_lock.try_acquire_process_lock(self.base)[0])
        profile_lock.release_process_lock(self.base)
        # After release the internal registry is empty; re-acquire succeeds.
        self.assertTrue(profile_lock.try_acquire_process_lock(self.base)[0])

    def test_service_calls_still_work_under_lock(self):
        from litebrowser.services import personal_service

        self.assertTrue(profile_lock.try_acquire_process_lock(self.base)[0])
        note = personal_service.create_note(self.base, "Locked", "body")
        self.assertTrue(note["id"])


if __name__ == "__main__":
    unittest.main()
