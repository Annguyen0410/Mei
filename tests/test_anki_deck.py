"""Anki interchange: what an .apkg import keeps, and what an export carries out.

The packages in here are built by hand (zipfile + sqlite3, exactly what Anki
writes) rather than committed as binary fixtures: a legacy package with a Basic
model, a zstd-shaped one whose decoder is injected, and our own export read back
by Anki's schema rules. The point of the file is that a round trip through Anki
loses nothing Mei cares about — front, back, interval, ease — and that a deck the
user cannot import says *why* instead of showing a traceback.
"""
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest import mock

from litebrowser.core import prefs
from litebrowser.services import anki_service, flashcard_service, history_service

_SEP = "\x1f"


def _legacy_collection(path: str, notes: list[tuple[str, str, str]], scheduling=None) -> bytes:
    """Write a version-11 collection the way Anki does, and return its bytes."""
    scheduling = scheduling or {}
    now = 1700000000
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE col (id integer primary key, crt integer, mod integer, scm integer, ver integer,
            dty integer, usn integer, ls integer, conf text, models text, decks text, dconf text, tags text);
        CREATE TABLE notes (id integer primary key, guid text, mid integer, mod integer, usn integer,
            tags text, flds text, sfld integer, csum integer, flags integer, data text);
        CREATE TABLE cards (id integer primary key, nid integer, did integer, ord integer, mod integer,
            usn integer, type integer, queue integer, due integer, ivl integer, factor integer,
            reps integer, lapses integer, left integer, odue integer, odid integer, flags integer, data text);
        """
    )
    connection.execute(
        "INSERT INTO col VALUES (1,?,?,?,11,0,0,0,'{}',?,?,'{}','{}')",
        (now, now, now, json.dumps({"1": {"id": 1, "name": "Basic", "flds": [], "tmpls": []}}), json.dumps({"1": {"id": 1, "name": "Deck"}})),
    )
    for index, (front, back, tags) in enumerate(notes):
        note_id = 1600000000000 + index
        connection.execute(
            "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,0,'')",
            (note_id, f"guid{index}", 1, now, -1, f" {tags} " if tags else " ", front + _SEP + back, front, index),
        )
        ivl, factor, reps, lapses = scheduling.get(index, (0, 0, 0, 0))
        connection.execute(
            "INSERT INTO cards VALUES (?,?,?,0,?,-1,2,2,?,?,?,?,?,0,0,0,0,'')",
            (note_id + 1, note_id, 1, now, ivl, ivl, factor, reps, lapses),
        )
    connection.commit()
    connection.close()
    with open(path, "rb") as handle:
        return handle.read()


def _write_package(path: str, name: str, payload: bytes, extras: dict | None = None) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(name, payload)
        package.writestr("media", b"{}")
        for extra_name, extra_payload in (extras or {}).items():
            package.writestr(extra_name, extra_payload)
    return path


class _ProfileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "profile"))
        self.folder = os.path.join(self._tmp.name, "decks")
        os.makedirs(self.folder, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _legacy_package(self, notes, scheduling=None, name="collection.anki2") -> str:
        with tempfile.TemporaryDirectory() as scratch:
            raw = _legacy_collection(os.path.join(scratch, "c.anki2"), notes, scheduling)
        return _write_package(os.path.join(self.folder, "deck.apkg"), name, raw)


class TestImport(_ProfileCase):
    def test_a_legacy_package_lands_as_cards(self):
        path = self._legacy_package([("What is 2+2?", "4", ""), ("Capital of France?", "Paris", "")])
        report = anki_service.import_package(self.base, path)
        self.assertEqual(report["imported"], 2)
        self.assertEqual(report["duplicates"], 0)
        self.assertEqual(report["deck"], "deck", "the file name names the deck")
        fronts = {card["front"] for card in flashcard_service.load_cards(self.base)}
        self.assertEqual(fronts, {"What is 2+2?", "Capital of France?"})
        logged = history_service.list_activity(self.base, kind="flashcard")[0]
        self.assertEqual((logged["title"], logged["detail"]), ("deck", "Imported 2 cards"))

    def test_interval_and_ease_travel_with_the_card(self):
        path = self._legacy_package([("Q", "A", "")], scheduling={0: (21, 2600, 7, 2)})
        anki_service.import_package(self.base, path)
        card = flashcard_service.load_cards(self.base)[0]
        self.assertEqual(card["interval"], 21)
        self.assertEqual(card["ease"], 2.6)
        self.assertEqual(card["reviews"], 7)
        self.assertEqual(card["lapses"], 2)
        self.assertTrue(flashcard_service.due_cards(self.base), "an import is ready to practice now")

    def test_html_sound_tags_and_extra_fields_become_plain_text(self):
        path = self._legacy_package(
            [("What is <b>HTML</b>?<br>really", "Markup &amp; more[sound:clip.mp3]\x1fthird field", "ch1 ch2")]
        )
        anki_service.import_package(self.base, path)
        card = flashcard_service.load_cards(self.base)[0]
        self.assertEqual(card["front"], "What is HTML?\nreally")
        self.assertIn("Markup & more", card["back"])
        self.assertNotIn("[sound:", card["back"])
        self.assertIn("third field", card["back"])
        self.assertIn("#ch1 #ch2", card["back"])

    def test_a_card_without_a_back_is_skipped_and_counted(self):
        path = self._legacy_package([("Only a front", "", ""), ("Real", "Card", "")])
        report = anki_service.import_package(self.base, path)
        self.assertEqual((report["imported"], report["skipped"]), (1, 1))

    def test_re_importing_the_same_deck_adds_nothing(self):
        path = self._legacy_package([("Q", "A", "")])
        anki_service.import_package(self.base, path)
        report = anki_service.import_package(self.base, path)
        self.assertEqual((report["imported"], report["duplicates"]), (0, 1))
        self.assertEqual(len(flashcard_service.load_cards(self.base)), 1)

    def test_media_is_reported_not_imported(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = _legacy_collection(os.path.join(scratch, "c.anki2"), [("Q", "A", "")])
        path = _write_package(
            os.path.join(self.folder, "media.apkg"),
            "collection.anki2",
            raw,
            extras={"0": b"jpeg-bytes", "1": b"mp3-bytes"},
        )
        report = anki_service.import_package(self.base, path)
        self.assertEqual(report["media"], 2)
        self.assertEqual(report["imported"], 1)

    def test_a_zstd_collection_without_a_decoder_names_the_fix(self):
        path = self._legacy_package([("Q", "A", "")], name="collection.anki21")
        with mock.patch.object(anki_service, "_load_decompressor", return_value=(None, None)):
            with self.assertRaises(anki_service.AnkiFormatError) as caught:
                anki_service.import_package(self.base, path)
        self.assertIn("zstandard", str(caught.exception))
        self.assertIn("Anki 2.1.50", str(caught.exception))

    def test_a_zstd_collection_is_read_through_the_decoder(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = _legacy_collection(os.path.join(scratch, "c.anki2"), [("Compressed", "Deck", "")])
        path = _write_package(os.path.join(self.folder, "zstd.apkg"), "collection.anki21b", b"zstd-frame")
        seen = {}

        def fake_decoder(data: bytes) -> bytes:
            seen["payload"] = data
            return raw

        with mock.patch.object(anki_service, "_load_decompressor", return_value=("fake", fake_decoder)):
            report = anki_service.import_package(self.base, path)
        self.assertEqual(report["imported"], 1)
        self.assertEqual(seen["payload"], b"zstd-frame")
        self.assertEqual(flashcard_service.load_cards(self.base)[0]["front"], "Compressed")

    def test_a_missing_or_broken_package_says_what_is_wrong(self):
        with self.assertRaises(anki_service.AnkiFormatError):
            anki_service.import_package(self.base, os.path.join(self.folder, "nothing.apkg"))
        broken = os.path.join(self.folder, "broken.apkg")
        with open(broken, "wb") as handle:
            handle.write(b"not a zip at all")
        with self.assertRaises(anki_service.AnkiFormatError):
            anki_service.import_package(self.base, broken)
        empty = os.path.join(self.folder, "empty.apkg")
        _write_package(empty, "readme.txt", b"hello")
        with self.assertRaises(anki_service.AnkiFormatError) as caught:
            anki_service.import_package(self.base, empty)
        self.assertIn("collection.anki2", str(caught.exception))


class TestExport(_ProfileCase):
    def _cards(self, count: int = 2) -> None:
        for index in range(count):
            card = flashcard_service.add_card(self.base, f"Front {index}", f"Back {index}")
            if index == 0:
                flashcard_service.review_card(self.base, card["id"], "good")

    def test_the_package_is_a_collection_anki_can_open(self):
        self._cards()
        out = os.path.join(self.folder, "mei.apkg")
        report = anki_service.export_package(self.base, out, deck_name="Study deck")
        self.assertEqual(report["cards"], 2)
        self.assertTrue(os.path.getsize(out) > 0)
        with zipfile.ZipFile(out) as package:
            self.assertIn("collection.anki2", package.namelist())
            self.assertIn("media", package.namelist())
            payload = package.read("collection.anki2")
        with tempfile.TemporaryDirectory() as scratch:
            db_path = os.path.join(scratch, "collection.anki2")
            with open(db_path, "wb") as handle:
                handle.write(payload)
            connection = sqlite3.connect(db_path)
            col = connection.execute("SELECT ver, crt, models, decks FROM col").fetchone()
            ver, crt, models, decks = col
            notes = connection.execute("SELECT flds FROM notes ORDER BY id").fetchall()
            cards = connection.execute("SELECT ivl, factor, type, queue, due FROM cards ORDER BY id").fetchall()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            connection.close()
        self.assertEqual(ver, 11)
        self.assertEqual({row[0].split(_SEP)[0] for row in notes}, {"Front 0", "Front 1"})
        self.assertEqual({name for name in tables}, {"col", "notes", "cards", "revlog", "graves"})
        self.assertEqual(json.loads(models)["1700000002"]["name"], "Basic (Mei)")
        self.assertEqual(json.loads(decks)["1700000001"]["name"], "Study deck")
        self.assertGreater(crt, 0)
        studied = [row for row in cards if row[0] > 0]
        self.assertEqual(len(studied), 1, "the reviewed card carries its interval")
        self.assertEqual((studied[0][2], studied[0][3]), (2, 2), "an interval card exports as a review card")
        fresh = [row for row in cards if row[0] == 0]
        self.assertEqual((fresh[0][2], fresh[0][3]), (0, 0), "an unpracticed card exports as new")

    def test_a_round_trip_keeps_everything_mei_knows(self):
        self._cards()
        before = {card["front"]: card for card in flashcard_service.load_cards(self.base)}
        out = os.path.join(self.folder, "mei.apkg")
        anki_service.export_package(self.base, out)
        other = prefs.ensure_profile_layout(os.path.join(self._tmp.name, "other"))
        report = anki_service.import_package(other, out)
        self.assertEqual(report["imported"], 2)
        after = {card["front"]: card for card in flashcard_service.load_cards(other)}
        for front, card in before.items():
            self.assertEqual(after[front]["back"], card["back"])
            self.assertEqual(after[front]["ease"], card["ease"], "ease survives as per-mille")
            # Anki counts whole days, so a fractional interval exports below itself
            # (2.5 days → 2) — the one thing a round trip is allowed to lose.
            self.assertEqual(after[front]["interval"], int(float(card["interval"])))

    def test_an_empty_deck_still_writes_a_readable_package(self):
        out = os.path.join(self.folder, "empty.apkg")
        report = anki_service.export_package(self.base, out)
        self.assertEqual(report["cards"], 0)
        self.assertEqual(anki_service.import_package(self.base, out)["imported"], 0)

    def test_the_export_is_logged_for_the_history_page(self):
        self._cards(1)
        anki_service.export_package(self.base, os.path.join(self.folder, "mei.apkg"))
        self.assertEqual(history_service.list_activity(self.base, kind="flashcard")[0]["detail"], "Exported 1 cards")


if __name__ == "__main__":
    unittest.main()
