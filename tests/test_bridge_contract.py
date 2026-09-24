"""Phone bridge contract: what ``/capabilities`` promises must be dispatched.

The Android app is developed outside this repository, so the only thing keeping
the two sides honest is this server. Before this test, a new action could be
advertised in ``SUPPORTED_ACTIONS`` while nothing in ``dispatch_ingest`` handled
it — the phone would get a silent "unknown action".
"""
import inspect
import re
import unittest

from litebrowser.services import android_bridge_service as bridge


class TestAdvertisedActionsAreDispatched(unittest.TestCase):
    def _dispatch_source(self) -> str:
        return inspect.getsource(bridge.dispatch_ingest)

    def test_every_supported_action_has_a_branch(self):
        src = self._dispatch_source()
        for action in bridge.SUPPORTED_ACTIONS:
            with self.subTest(action=action):
                self.assertIn(f'action == "{action}"', src)

    def test_dispatch_does_not_handle_undisclosed_actions(self):
        handled = set(re.findall(r'action == "([a-z_]+)"', self._dispatch_source()))
        self.assertTrue(handled)
        self.assertEqual(handled - set(bridge.SUPPORTED_ACTIONS), set())

    def test_actions_are_unique_and_snake_case(self):
        actions = list(bridge.SUPPORTED_ACTIONS)
        self.assertEqual(len(actions), len(set(actions)))
        for action in actions:
            with self.subTest(action=action):
                self.assertRegex(action, r"^[a-z][a-z0-9_]*$")


class TestVersionedContract(unittest.TestCase):
    def test_protocol_version_is_an_int(self):
        self.assertIsInstance(bridge.API_VERSION, int)

    def test_both_discovery_endpoints_advertise_the_version(self):
        src = inspect.getsource(bridge._BridgeRequestHandler)
        self.assertIn('"protocol_version": API_VERSION', src)
        # ping must not re-invent the version literal
        self.assertNotIn('"protocol_version": 1', src)


if __name__ == "__main__":
    unittest.main()
