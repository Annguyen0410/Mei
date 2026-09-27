"""The bridge as the Mei extension sees it: real HTTP, real preflight, real CORS.

The Chrome/Edge extension used to export a JSON/ZIP of your tabs and ask you to
import it by hand. It can now talk to the bridge directly — which means the
*protocol* became a security surface, and this file pins it:

* a preflight from an extension origin is answered, and the response carries the
  CORS headers the extension needs;
* a preflight from a web page is still refused, and a web page never gets a
  readable CORS answer — the token stops it doing anything, CORS stops it from
  quietly trying;
* the token is required from an extension too (with CORS preserved on the 401, so
  the extension can say "pair with Mei first" instead of "network error");
* ``save_selection`` really writes a note / card / saved page, and refuses an
  empty selection with a message instead of an empty record.

Requests are made exactly as the extension makes them: ``Origin: chrome-extension://…``
plus a Bearer token, against a real server on a loopback port.
"""
import json
import os
import socket
import tempfile
import unittest
import urllib.error
import urllib.request

from litebrowser.core import prefs
from litebrowser.services import android_bridge_service, flashcard_service, life_service, personal_service

EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
WEB_ORIGIN = "https://evil.example"
TOKEN = "secret-test-token"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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

    def _call(self, path, method="GET", data=None, origin="", token=TOKEN):
        url = f"http://127.0.0.1:{self.port}{path}"
        headers = {}
        if origin:
            headers["Origin"] = origin
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        return urllib.request.urlopen(request, timeout=5)

    def _ingest(self, action, payload, origin=EXTENSION_ORIGIN, token=TOKEN):
        response = self._call(
            "/api/mobile/ingest",
            method="POST",
            data={"action": action, "source": "extension.mei_bridge", "payload": payload},
            origin=origin,
            token=token,
        )
        return response, json.loads(response.read().decode("utf-8"))


class TestExtensionCors(_Bridge):
    def test_a_preflight_from_an_extension_is_answered(self):
        response = self._call("/api/mobile/ingest", method="OPTIONS", origin=EXTENSION_ORIGIN, token="")
        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), EXTENSION_ORIGIN)
        self.assertIn("Authorization", response.headers.get("Access-Control-Allow-Headers", ""))
        self.assertIn("POST", response.headers.get("Access-Control-Allow-Methods", ""))
        self.assertEqual(response.headers.get("Vary"), "Origin")

    def test_a_preflight_from_a_web_page_is_refused_without_cors(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._call("/api/mobile/ingest", method="OPTIONS", origin=WEB_ORIGIN, token="")
        self.assertEqual(ctx.exception.code, 405)
        self.assertIsNone(ctx.exception.headers.get("Access-Control-Allow-Origin"))
        self.assertIn("browser extensions only", ctx.exception.read().decode("utf-8"))

    def test_an_extension_without_the_token_gets_a_readable_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._call("/api/mobile/ping", origin=EXTENSION_ORIGIN, token="")
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(
            ctx.exception.headers.get("Access-Control-Allow-Origin"),
            EXTENSION_ORIGIN,
            "the extension has to be able to read the refusal instead of reporting a network error",
        )

    def test_a_web_origin_never_gets_a_readable_answer(self):
        response, body = self._ingest("save_page", {"url": "https://example.com/x", "title": "X"}, origin=WEB_ORIGIN)
        self.assertEqual(response.status, 200)
        self.assertTrue(body["ok"])
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"), "a page must not read bridge replies")

    def test_only_a_clean_extension_origin_comes_back_in_the_answer(self):
        """The Origin is rebuilt as scheme://host — nothing a caller sends is echoed raw."""
        cases = {
            EXTENSION_ORIGIN + "/": EXTENSION_ORIGIN,
            EXTENSION_ORIGIN + "/../evil": EXTENSION_ORIGIN,
            EXTENSION_ORIGIN + "?x=1#y": EXTENSION_ORIGIN,
        }
        for sent, expected in cases.items():
            with self.subTest(origin=sent):
                response = self._call("/api/mobile/ping", origin=sent)
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), expected)

    def test_a_dirty_or_opaque_origin_is_not_reflected(self):
        for sent in ("null", "chrome-extension://", "chrome-extension://a, https://evil.example", "file:///C:/x.html"):
            with self.subTest(origin=sent):
                response = self._call("/api/mobile/ping", origin=sent)
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"), "nothing to reflect")


class TestSendSelection(_Bridge):
    def test_a_tab_can_be_sent_to_mei(self):
        response, body = self._ingest("save_page", {"url": "https://example.com/krebs", "title": "Krebs cycle"})
        self.assertTrue(body["ok"])
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), EXTENSION_ORIGIN)
        pages = life_service.load_saved_pages(self.base)
        self.assertEqual([page["title"] for page in pages], ["Krebs cycle"])

    def test_a_selection_becomes_a_note_with_its_source(self):
        _response, body = self._ingest(
            "save_selection",
            {"text": "citrate, isocitrate", "url": "https://example.com/krebs", "title": "Krebs note"},
        )
        self.assertTrue(body["ok"], body)
        notes = personal_service.list_notes(self.base)
        self.assertEqual([note["title"] for note in notes], ["Krebs note"])
        self.assertIn("citrate, isocitrate", notes[0]["content"])
        self.assertIn("Source: https://example.com/krebs", notes[0]["content"])
        self.assertEqual(notes[0]["category"], "Clippings")

    def test_a_selection_can_be_a_card_or_a_saved_page(self):
        _response, card_body = self._ingest(
            "save_selection",
            {"text": "7 layers", "as": "card", "front": "How many OSI layers?", "tags": ["networking"]},
        )
        self.assertTrue(card_body["ok"], card_body)
        cards = flashcard_service.load_cards(self.base)
        self.assertEqual(cards[0]["front"], "How many OSI layers?")
        self.assertIn("7 layers", cards[0]["back"])
        self.assertIn("#networking", cards[0]["back"])

        _response, page_body = self._ingest(
            "save_selection",
            {"text": "the whole page", "as": "saved_page", "url": "https://example.com/osI", "title": "OSI"},
        )
        self.assertTrue(page_body["ok"], page_body)
        self.assertEqual([page["url"] for page in life_service.load_saved_pages(self.base)], ["https://example.com/osI"])

    def test_an_empty_selection_is_refused_with_a_message(self):
        _response, body = self._ingest("save_selection", {"text": "   ", "url": "https://example.com"})
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_payload")
        self.assertEqual(personal_service.list_notes(self.base), [])

    def test_the_action_is_advertised_to_the_extension(self):
        response = self._call("/api/mobile/ping", origin=EXTENSION_ORIGIN)
        payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("save_selection", payload["capabilities"])
        self.assertIn("save_page", payload["capabilities"])


if __name__ == "__main__":
    unittest.main()
