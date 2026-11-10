"""Hibernation may not discard a tab that is doing work.

The old timer hibernated any background tab after N seconds — including one
playing audio or downloading. These tests pin the conservative policy: when a
state cannot be proven safe, the answer is "do not hibernate".
"""
import unittest

from litebrowser.browser import hibernation_policy as policy


def _state(**overrides):
    base = dict(ms_since_last_active=400_000)
    base.update(overrides)
    return policy.TabState(**base)


class TestBlockers(unittest.TestCase):
    def test_a_quiet_idle_background_tab_may_hibernate(self):
        self.assertEqual(policy.hibernate_block_reason(_state(), 300), "")

    def test_active_tab_is_never_hibernated(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_active=True), 300), policy.REASON_ACTIVE
        )

    def test_pinned_and_never_tabs_are_exempt(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_pinned=True), 300), policy.REASON_PINNED
        )
        self.assertEqual(
            policy.hibernate_block_reason(_state(never_hibernate=True), 300), policy.REASON_NEVER
        )

    def test_private_tabs_are_never_discarded_automatically(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_incognito=True), 300), policy.REASON_INCOGNITO
        )

    def test_audio_blocks_hibernation_even_when_idle(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_audible=True), 300), policy.REASON_AUDIBLE
        )

    def test_a_running_download_blocks_hibernation(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(has_active_download=True), 300),
            policy.REASON_DOWNLOAD,
        )

    def test_a_navigation_in_flight_blocks_hibernation(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_navigating=True), 300),
            policy.REASON_NAVIGATING,
        )

    def test_unknown_idleness_is_treated_as_not_idle(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(ms_since_last_active=-1), 300),
            policy.REASON_TOO_SOON,
        )

    def test_a_recently_used_tab_is_not_hibernated(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(ms_since_last_active=1_000), 300),
            policy.REASON_TOO_SOON,
        )

    def test_disabling_hibernation_blocks_everything(self):
        self.assertEqual(policy.hibernate_block_reason(_state(), 0), "disabled")

    def test_an_already_dormant_tab_is_not_hibernated_twice(self):
        self.assertEqual(
            policy.hibernate_block_reason(_state(is_hibernated=True), 300),
            "already_hibernated",
        )

    def test_every_reason_has_user_facing_text(self):
        reasons = (
            policy.REASON_ACTIVE,
            policy.REASON_AUDIBLE,
            policy.REASON_DOWNLOAD,
            policy.REASON_INCOGNITO,
            policy.REASON_NAVIGATING,
            policy.REASON_NEVER,
            policy.REASON_PINNED,
            policy.REASON_TOO_SOON,
            "disabled",
            "already_hibernated",
            "something_new",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                text = policy.describe_reason(reason)
                self.assertTrue(text)
                self.assertNotEqual(text, reason)


if __name__ == "__main__":
    unittest.main()
