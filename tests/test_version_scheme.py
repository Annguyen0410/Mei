"""Pre-1.0 version scheme: 0.6.8.0 tuples compare correctly."""
import unittest

from litebrowser.services import update_service


class TestVersionScheme(unittest.TestCase):
    def test_normalize_four_part(self):
        self.assertEqual(update_service._normalize_version("0.6.8.0"), (0, 6, 8, 0))

    def test_newer_remote_detected(self):
        self.assertGreater(
            update_service._normalize_version("0.6.9"),
            update_service._normalize_version("0.6.8.0"),
        )

    def test_older_remote_not_detected(self):
        self.assertLessEqual(
            update_service._normalize_version("0.6.7"),
            update_service._normalize_version("0.6.8.0"),
        )

    def test_milestone_jump_detected(self):
        # When pre-1.0 finally graduates: 1.0.0 beats every 0.x.
        self.assertGreater(
            update_service._normalize_version("1.0.0"),
            update_service._normalize_version("0.6.8.0"),
        )

    def test_non_numeric_chunk_safe(self):
        self.assertEqual(
            update_service._normalize_version("0.6.8.0-beta"),
            (0, 6, 8, 0),
        )


if __name__ == "__main__":
    unittest.main()
