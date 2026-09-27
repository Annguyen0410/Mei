"""The bridge's other direction: the phone asks what is on the desk.

Ingest actions let the phone write *into* Mei. ``GET /api/mobile/today`` is the
answer back — "hôm nay học gì?" — so the phone can show the same four blocks
Home opens on, plus the four numbers a widget prints (on the plate, waiting,
left open, cards due) and the loop's single next step.

What this file pins, in order of how easily it could go wrong:

* the payload is *the desk*, not a second opinion about the desk (same four
  block keys the Home page renders, from ``desk_service``);
* a ``?day=`` parameter moves the day (so a phone in another time zone, or a
  test, can ask about a specific date) but a junk value falls back to today
  instead of reaching ``datetime.strptime`` and becoming a 500;
* reading costs nothing: two reads leave every file in the profile byte-identical;
* it is still behind the token, and a web page still gets no CORS answer.
"""
import json
import os
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from litebrowser.core import prefs
from litebrowser.services import android_bridge_service, desk_service, flashcard_service, life_service, personal_plan

EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
TOKEN = "secret-test-token"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _day(offset: int = 0) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _snapshot(root: str) -> dict:
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            out[os.path.relpath(path, root)] = (stat.st_size, stat.st_mtime_ns)
    return out


class _Bridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        prefs.set_mobile_bridge_enabled(self.base, True)
        prefs.set_mobile_bridge_host(self.base, "127.0.0.1")
        prefs.set_mobile_bridge_port(self.base, _pick_free_port())
        prefs.set_mobile_bridge_token(self.base, TOKEN)
        android_bridge_service.stop()
        self.assertTrue(android_bridge_service.start(self.base))
        address = android_bridge_service.listen_address()
        self.assertIsNotNone(address)
        self.port = address[1]

    def tearDown(self):
        android_bridge_service.stop()
        self._tmp.cleanup()

    def _call(self, path, token=TOKEN, origin=""):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin:
            headers["Origin"] = origin
        url = f"http://127.0.0.1:{self.port}{path}"
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5)

    def _today(self, query="", token=TOKEN, origin=""):
        response = self._call("/api/mobile/today" + query, token=token, origin=origin)
        return response, json.loads(response.read().decode("utf-8"))


class TestPhoneDesk(_Bridge):
    def test_the_phone_gets_the_same_four_blocks_home_opens_on(self):
        _response, body = self._today()
        self.assertTrue(body["ok"], body)
        self.assertEqual([block["key"] for block in body["blocks"]], list(desk_service.DESK_BLOCKS))
        for block in body["blocks"]:
            self.assertTrue(block["title"], block)
            self.assertIsInstance(block["count"], int)
            self.assertIn("empty", block)
            self.assertIsInstance(block["rows"], list)
        self.assertEqual(body["date"], _day())
        self.assertTrue(body["headline"], "a widget needs one line to print")
        self.assertIsInstance(body["steps"], list)
        self.assertEqual(sorted(body["numbers"]), ["cards_due", "left_open", "on_the_plate", "waiting"])
        self.assertEqual(body["protocol_version"], android_bridge_service.API_VERSION)

    def test_todays_work_and_the_cards_owed_reach_the_phone(self):
        personal_plan.create_item(self.base, "Essay draft", due_date=_day(), kind="assignment")
        life_service.add_task(self.base, "Buy milk", bucket="today")
        flashcard_service.add_card(self.base, "How many OSI layers?", "7")

        _response, body = self._today()
        today_block = desk_service.block_by_key({"blocks": body["blocks"]}, "today")
        titles = [row.get("title", "") for row in today_block["rows"]]
        self.assertIn("Essay draft", titles)
        self.assertIn("Buy milk", titles)
        due_block = desk_service.block_by_key({"blocks": body["blocks"]}, "due")
        self.assertTrue(
            any("card" in row.get("title", "") for row in due_block["rows"]),
            f"the cards owed should be visible: {due_block['rows']}",
        )
        self.assertEqual(body["numbers"]["cards_due"], 1)
        self.assertEqual(body["numbers"]["on_the_plate"], 2)
        next_step = body["next"] or {}
        self.assertIn("Essay draft", next_step.get("label", ""), "the loop's next step should name the item a phone would surface")

    def test_the_day_parameter_moves_the_day_a_phone_asks_about(self):
        personal_plan.create_item(self.base, "Due today", due_date=_day())
        personal_plan.create_item(self.base, "Due tomorrow", due_date=_day(1))

        _response, today = self._today()
        _response, tomorrow = self._today(f"?day={_day(1)}")
        self.assertEqual(tomorrow["date"], _day(1))
        self.assertIn("Due today", [row.get("title") for row in desk_service.block_by_key({"blocks": today["blocks"]}, "today")["rows"]])
        self.assertIn(
            "Due tomorrow",
            [row.get("title") for row in desk_service.block_by_key({"blocks": tomorrow["blocks"]}, "today")["rows"]],
            "asking about tomorrow must answer about tomorrow",
        )

    def test_a_junk_day_parameter_is_today_not_a_crash(self):
        for query in ("?day=not-a-date", "?day=2026-13-45", "?day=", "?day=2026-9-6", "?day=99999999-99-99"):
            with self.subTest(query=query):
                response, body = self._today(query)
                self.assertEqual(response.status, 200)
                self.assertEqual(body["date"], _day(), "a junk day must fall back to today")

    def test_reading_the_desk_does_not_write_to_the_profile(self):
        personal_plan.create_item(self.base, "Essay draft", due_date=_day())
        flashcard_service.add_card(self.base, "Q", "A")
        before = _snapshot(self.base)
        self._today()
        self._today(f"?day={_day(2)}")
        android_bridge_service.desk_for_phone(self.base)
        self.assertEqual(_snapshot(self.base), before, "a read endpoint must not touch the profile")

    def test_the_read_door_still_needs_the_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._today(token="")
        self.assertEqual(ctx.exception.code, 401)

    def test_a_web_page_gets_no_readable_answer(self):
        response, body = self._today(origin="https://evil.example")
        self.assertTrue(body["ok"])
        self.assertIsNone(
            response.headers.get("Access-Control-Allow-Origin"),
            "a page must not be able to read the desk, token or not",
        )
        extension_response, _body = self._today(origin=EXTENSION_ORIGIN)
        self.assertEqual(extension_response.headers.get("Access-Control-Allow-Origin"), EXTENSION_ORIGIN)

    def test_the_endpoint_is_advertised_to_whoever_can_call_it(self):
        response = self._call("/api/mobile/capabilities")
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["read"]["today"], "/api/mobile/today")
        self.assertTrue(payload["read"]["day_param"])


if __name__ == "__main__":
    unittest.main()
