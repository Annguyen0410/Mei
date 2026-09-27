"""Anki interchange: import an .apkg deck, export this one back.

An .apkg is a zip around a SQLite collection, in one of two shapes:
- ``collection.anki2`` — plain SQLite: what Anki wrote before 2.1.50, and what
  this module writes (Anki still imports that shape and upgrades it).
- ``collection.anki21`` / ``collection.anki21b`` — the same SQLite compressed
  with zstd (Anki 2.1.50+). Nothing in the project depends on a zstd decoder, so
  the reader looks for ``zstandard``, then ``pyzstd``, then a ``zstd`` binary and,
  when none is present, raises :class:`AnkiFormatError` that names the fix rather
  than leaking a decompression traceback into a message box.

Mapping: Anki stores one note as fields joined by ``\\x1f``; field 0 becomes the
front and the rest the back, as plain text (HTML, ``[sound:…]`` and ``<img>``
carry no meaning in a Mei card), with Anki's tags appended as ``#tag`` lines.
``ivl``/``factor`` restore interval/ease so an already-studied deck keeps its
schedule, but every imported card is due now: Anki's ``due`` is a day count
relative to *its own* collection creation, and guessing that would schedule a
deck years into the future. ``media`` is counted and reported, not imported.
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile

from litebrowser.services import flashcard_service, history_service

# Anki's field separator inside notes.flds.
FIELD_SEPARATOR = "\x1f"

_COLLECTION_NAMES = ("collection.anki21b", "collection.anki21", "collection.anki2")
_COMPRESSED_NAMES = ("collection.anki21b", "collection.anki21")
_EASE_MIN, _EASE_MAX = 1.3, 3.0
_DECK_ID = 1700000001
_MODEL_ID = 1700000002
_ZSTD_HINT = (
    "This deck was exported by Anki 2.1.50 or newer, which zstd-compresses its "
    "collection. Install the decoder (pip install zstandard), or re-export the "
    "deck from Anki with \"Support older Anki versions\" ticked."
)

_SOUND_RE = re.compile(r"\[sound:[^\]]*\]", re.I)
_BLOCK_TAG_RE = re.compile(r"<(?:br|/div|/p|/li|/tr|/h[1-6])[^>]*>", re.I)
_IMG_RE = re.compile(r"<img[^>]*>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")

# The legacy collection schema (version 11) — the shape Anki's importer expects.
_SCHEMA = """
CREATE TABLE col (id integer primary key, crt integer not null, mod integer not null,
    scm integer not null, ver integer not null, dty integer not null, usn integer not null,
    ls integer not null, conf text not null, models text not null, decks text not null,
    dconf text not null, tags text not null);
CREATE TABLE notes (id integer primary key, guid text not null, mid integer not null,
    mod integer not null, usn integer not null, tags text not null, flds text not null,
    sfld integer not null, csum integer not null, flags integer not null, data text not null);
CREATE TABLE cards (id integer primary key, nid integer not null, did integer not null,
    ord integer not null, mod integer not null, usn integer not null, type integer not null,
    queue integer not null, due integer not null, ivl integer not null, factor integer not null,
    reps integer not null, lapses integer not null, left integer not null, odue integer not null,
    odid integer not null, flags integer not null, data text not null);
CREATE TABLE revlog (id integer primary key, cid integer not null, usn integer not null,
    ease integer not null, ivl integer not null, lastIvl integer not null,
    factor integer not null, time integer not null, type integer not null);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE INDEX ix_notes_usn on notes (usn);
CREATE INDEX ix_cards_usn on cards (usn);
CREATE INDEX ix_cards_nid on cards (nid);
CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_revlog_cid on revlog (cid);
"""


class AnkiFormatError(ValueError):
    """A package this module cannot read, with a reason a user can act on."""


def import_package(base_dir: str, path: str, deck_name: str = "") -> dict:
    """Copy the cards of an .apkg into this profile's deck.

    Returns ``{deck, imported, duplicates, skipped, media, path}``. Cards that
    are already in the deck (same front and back) are counted as duplicates
    instead of being added twice, so re-importing an updated export is safe.
    """
    if not os.path.isfile(path):
        raise AnkiFormatError(f"There is no file to import at {path}.")
    try:
        package = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise AnkiFormatError("That file is not an Anki deck — an .apkg is a zip archive.") from exc
    with package:
        raw, compressed = _collection_bytes(package)
        media = sum(1 for name in package.namelist() if name.isdigit())
    if compressed:
        raw = _decompress_zstd(raw)

    name = (deck_name or "").strip() or os.path.splitext(os.path.basename(path))[0] or "Imported deck"
    existing = {
        ((card.get("front") or "").strip().casefold(), (card.get("back") or "").strip().casefold())
        for card in flashcard_service.load_cards(base_dir)
    }
    prepared: list[dict] = []
    duplicates = 0
    skipped = 0
    for note in _read_notes(raw):
        card = flashcard_service.new_card(note["front"], note["back"])
        if not card["front"] or not card["back"]:
            skipped += 1
            continue
        key = (card["front"].casefold(), card["back"].casefold())
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        card.update(
            {
                "ease": note["ease"],
                "interval": note["interval"],
                "due": note["due"],
                "reviews": note["reviews"],
                "lapses": note["lapses"],
            }
        )
        prepared.append(card)

    inserted = flashcard_service.add_cards(base_dir, prepared)
    history_service.log_event(
        base_dir,
        "flashcard",
        name[:80],
        f"Imported {len(inserted)} cards",
        {"deck": name, "file": os.path.basename(path), "duplicates": duplicates, "skipped": skipped},
    )
    return {
        "deck": name,
        "imported": len(inserted),
        "duplicates": duplicates,
        "skipped": skipped,
        "media": media,
        "path": path,
    }


def export_package(base_dir: str, path: str, deck_name: str = "Mei deck") -> dict:
    """Write this profile's deck as an .apkg for Anki to open.

    Returns ``{deck, cards, bytes, path}``. Scheduling travels with the cards:
    a card with an interval becomes a review card due that many days out, so
    studying in Anki and re-importing does not restart the deck.
    """
    cards = [c for c in flashcard_service.load_cards(base_dir) if (c.get("front") or "").strip()]
    name = (deck_name or "").strip() or "Mei deck"
    now = int(time.time())
    with tempfile.TemporaryDirectory(prefix="mei-anki-") as folder:
        db_path = os.path.join(folder, "collection.anki2")
        _build_collection(db_path, cards, name, now)
        with open(db_path, "rb") as handle:
            payload = handle.read()
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("collection.anki2", payload)
        # Anki expects the media map next to the collection; Mei cards are text.
        package.writestr("media", b"{}")
    report = {"deck": name, "cards": len(cards), "bytes": os.path.getsize(path), "path": path}
    history_service.log_event(
        base_dir, "flashcard", name[:80], f"Exported {len(cards)} cards", {"deck": name, "file": os.path.basename(path)}
    )
    return report


def plain_text(field: str) -> str:
    """Anki field HTML → the plain text a Mei card shows."""
    text = _SOUND_RE.sub("", str(field or ""))
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _IMG_RE.sub("", text)
    text = _ANY_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _collection_bytes(package: zipfile.ZipFile) -> tuple[bytes, bool]:
    """The collection inside the package, plus whether it is zstd-compressed."""
    for name in _COLLECTION_NAMES:
        try:
            return package.read(name), name in _COMPRESSED_NAMES
        except KeyError:
            continue
    raise AnkiFormatError(
        "That package has no Anki collection inside it (looked for "
        + ", ".join(_COLLECTION_NAMES)
        + ")."
    )


def _load_decompressor():
    """``(name, callable)`` for a zstd decoder, or ``(None, None)`` when there is none."""
    try:
        import zstandard  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        def via_zstandard(data: bytes) -> bytes:
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:
                return reader.read()

        return "zstandard", via_zstandard

    try:
        import pyzstd  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        return "pyzstd", pyzstd.decompress

    binary = shutil.which("zstd")
    if binary:

        def via_binary(data: bytes) -> bytes:
            result = subprocess.run([binary, "-d", "--stdout"], input=data, capture_output=True)
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", "replace").strip()[:200]
                raise AnkiFormatError(f"The zstd binary could not unpack this deck: {detail}")
            return result.stdout

        return "zstd", via_binary
    return None, None


def _decompress_zstd(raw: bytes) -> bytes:
    name, decoder = _load_decompressor()
    if decoder is None:
        raise AnkiFormatError(_ZSTD_HINT)
    try:
        return decoder(raw)
    except AnkiFormatError:
        raise
    except Exception as exc:  # a broken frame should read as a bad deck, not a crash
        raise AnkiFormatError(f"{name} could not unpack this deck: {exc}") from exc


def _read_notes(raw: bytes) -> list[dict]:
    """``[{front, back, ease, interval, due, reviews, lapses}]`` from a collection."""
    with tempfile.TemporaryDirectory(prefix="mei-anki-") as folder:
        db_path = os.path.join(folder, "collection.anki2")
        with open(db_path, "wb") as handle:
            handle.write(raw)
        connection = sqlite3.connect(db_path)
        try:
            scheduling: dict[int, tuple[int, int, int, int]] = {}
            try:
                rows = connection.execute(
                    "SELECT nid, ivl, factor, reps, lapses FROM cards"
                ).fetchall()
            except sqlite3.DatabaseError:
                rows = []
            for nid, ivl, factor, reps, lapses in rows:
                scheduling.setdefault(
                    int(nid or 0), (int(ivl or 0), int(factor or 0), int(reps or 0), int(lapses or 0))
                )
            try:
                notes = connection.execute("SELECT id, flds, tags FROM notes").fetchall()
            except sqlite3.DatabaseError as exc:
                raise AnkiFormatError("The package's collection is not a readable Anki database.") from exc
        finally:
            connection.close()

    parsed: list[dict] = []
    now = int(time.time())
    for note_id, flds, tags in notes:
        fields = [plain_text(part) for part in str(flds or "").split(FIELD_SEPARATOR)]
        front = fields[0] if fields else ""
        back = "\n\n".join(part for part in fields[1:] if part)
        tag_list = [tag for tag in str(tags or "").split() if tag]
        if tag_list:
            back = (back + "\n\n" if back else "") + " ".join(f"#{tag}" for tag in tag_list)
        interval, factor, reps, lapses = scheduling.get(int(note_id or 0), (0, 0, 0, 0))
        ease = min(_EASE_MAX, max(_EASE_MIN, (factor / 1000.0) if factor else 2.5))
        parsed.append(
            {
                "front": front,
                "back": back,
                "ease": round(ease, 3),
                "interval": max(0, interval),
                "due": now,
                "reviews": max(0, reps),
                "lapses": max(0, lapses),
            }
        )
    return parsed


def _build_collection(db_path: str, cards: list[dict], deck_name: str, now: int) -> None:
    """Write a legacy (version 11) collection holding ``cards`` as one Basic model."""
    millis = now * 1000
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO col VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,
                now,
                now,
                millis,
                11,
                0,
                0,
                0,
                json.dumps(_conf()),
                _model_json(now),
                _deck_json(now, deck_name),
                json.dumps(_DEFAULT_DCONF),
                "{}",
            ),
        )
        for index, card in enumerate(cards):
            front = (card.get("front") or "").strip()
            back = (card.get("back") or "").strip()
            note_id = millis + index * 2
            flds = front + FIELD_SEPARATOR + back
            connection.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    note_id,
                    _guid(front),
                    _MODEL_ID,
                    now,
                    -1,
                    " ",
                    flds,
                    front,
                    int(hashlib.sha1(front.encode("utf-8")).hexdigest()[:8], 16),
                    0,
                    "",
                ),
            )
            interval = max(0, int(float(card.get("interval", 0) or 0)))
            ease = min(_EASE_MAX, max(_EASE_MIN, float(card.get("ease", 2.5) or 2.5)))
            # Review cards count their due date in days from col.crt, which this
            # export sets to *now* — so the interval carries over unchanged.
            card_type, queue, due = (2, 2, interval) if interval > 0 else (0, 0, index)
            connection.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    note_id + 1,
                    note_id,
                    _DECK_ID,
                    0,
                    now,
                    -1,
                    card_type,
                    queue,
                    due,
                    interval,
                    int(round(ease * 1000)),
                    max(0, int(card.get("reviews", 0) or 0)),
                    max(0, int(card.get("lapses", 0) or 0)),
                    0,
                    0,
                    0,
                    0,
                    "",
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _guid(front: str) -> str:
    """Anki's guid: base64 of a short hash, stable for the same front text."""
    digest = hashlib.sha1((front or "").encode("utf-8")).digest()[:8]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _model_field(name: str, order: int) -> dict:
    """One entry of the model's ``flds`` (Front and Back differ only by order)."""
    return {
        "name": name,
        "ord": order,
        "sticky": False,
        "rtl": False,
        "font": "Arial",
        "size": 20,
        "media": [],
        "prefs": None,
        "bqfmt": "",
        "bafmt": "",
    }


def _model_json(now: int) -> str:
    """``col.models``: a model id → Basic model map (Anki stores it in that shape)."""
    model = {
        "id": _MODEL_ID,
        "name": "Basic (Mei)",
        "type": 0,
        "mod": now,
        "usn": -1,
        "sortf": 0,
        "did": _DECK_ID,
        "tmpls": [
            {
                "name": "Card 1",
                "ord": 0,
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
                "bqfmt": "",
                "bafmt": "",
                "did": None,
                "bfont": "Arial",
                "bsize": 12,
            }
        ],
        "flds": [_model_field("Front", 0), _model_field("Back", 1)],
        "css": ".card {\n font-family: arial;\n font-size: 20px;\n text-align: center;\n"
        " color: black;\n background-color: white;\n}\n",
        "latexPre": "\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n"
        "\\usepackage[utf8]{inputenc}\n\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n"
        "\\setlength{\\parindent}{0in}\n\\begin{document}\n",
        "latexPost": "\\end{document}",
        "latexsvg": False,
        "req": [[0, "any", [0]]],
        "tags": [],
        "vers": [],
    }
    return json.dumps({str(_MODEL_ID): model}, ensure_ascii=False)


def _deck_json(now: int, name: str) -> str:
    return json.dumps(
        {
            str(_DECK_ID): {
                "id": _DECK_ID,
                "name": name,
                "mod": now,
                "usn": -1,
                "col": now,
                "desc": "",
                "dyn": 0,
                "collapsed": False,
                "browserCollapsed": False,
                "extendNew": 10,
                "extendRev": 50,
                "conf": 1,
                "lrnToday": [0, 0],
                "revToday": [0, 0],
                "newToday": [0, 0],
                "timeToday": [0, 0],
            }
        },
        ensure_ascii=False,
    )


def _conf() -> dict:
    return {
        "nextPos": 1,
        "estTimes": True,
        "activeDecks": [_DECK_ID],
        "sortType": "noteFld",
        "timeLim": 0,
        "sortBackwards": False,
        "addToCur": True,
        "curDeck": _DECK_ID,
        "newBury": True,
        "newSpread": 0,
        "dueCounts": True,
        "curModel": _MODEL_ID,
        "collapseTime": 1200,
    }


_DEFAULT_DCONF = {
    "1": {
        "id": 1,
        "name": "Default",
        "autoplay": True,
        "replayq": True,
        "mod": 0,
        "usn": 0,
        "maxTaken": 60,
        "timer": 0,
        "lapse": {"leechFails": 8, "minInt": 1, "delays": [10], "leechAction": 0, "mult": 0.0},
        "rev": {
            "perDay": 200,
            "ease4": 1.3,
            "fuzz": 0.05,
            "minSpace": 1,
            "ivlFct": 1.0,
            "maxIvl": 36500,
            "bury": True,
            "hardFactor": 1.2,
        },
        "new": {
            "delays": [1, 10],
            "ints": [1, 4, 7],
            "initialFactor": 2500,
            "bury": True,
            "order": 1,
            "perDay": 20,
            "separate": True,
        },
    }
}
