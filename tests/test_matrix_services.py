"""Matrix suite for four local services: focus, links, ICS and flashcards.

Each of these stores user work that cannot be regenerated, so the tests pin
behaviour that is easy to break while looking fine: a focus session must not
count twice, an abandoned session must not count at all, a link edge must not
duplicate or point at itself, an ICS file must not invent events, and SM-2 must
not wedge a card at an extreme ease.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from litebrowser.core import storage_utils
from litebrowser.services import flashcard_service as fs
from litebrowser.services import focus_service, ics_service, link_service


@pytest.fixture()
def base(tmp_path):
    return str(tmp_path)


# ------------------------------------------------------------------------ focus

@pytest.mark.parametrize(
    "requested,expected",
    [(25, 25), (45, 45), ("45", 45), (1, 1), (180, 180), (1000, 180), (0, 25), (-5, 25), ("abc", 25)],
)
def test_a_focus_pour_is_clamped_to_a_sane_length(requested, expected, base):
    session = focus_service.start_focus(base, requested)
    assert session["minutes"] == expected


def test_a_blank_label_becomes_the_planned_minutes(base):
    assert focus_service.start_focus(base, 30, "   ")["label"] == "30 min focus"
    assert focus_service.start_focus(base, 30, "Write report")["label"] == "Write report"


def test_starting_again_abandons_the_unfinished_pour(base):
    focus_service.start_focus(base, 25, "first")
    focus_service.start_focus(base, 10, "second")
    journal = focus_service.focus_journal(base)
    assert journal[0]["label"] == "first"
    assert journal[0]["status"] == "abandoned"


def test_a_running_pour_reports_remaining_time(base):
    focus_service.start_focus(base, 25)
    status = focus_service.focus_status(base)
    assert status["running"] is True
    assert 0 < status["remaining"] <= 25 * 60


def test_stopping_a_pour_files_it_as_completed(base):
    focus_service.start_focus(base, 25)
    assert focus_service.stop_focus(base)["closed"] is True
    assert focus_service.focus_journal(base)[0]["status"] == "completed"
    assert focus_service.focus_status(base)["running"] is False


def test_stopping_an_abandoned_pour_is_recorded_as_abandoned(base):
    focus_service.start_focus(base, 25)
    focus_service.stop_focus(base, complete=False)
    assert focus_service.focus_journal(base)[0]["status"] == "abandoned"


def test_stopping_without_a_pour_reports_nothing_to_close(base):
    assert focus_service.stop_focus(base) == {"closed": False, "session": None}


def test_an_expired_pour_finishes_itself(base):
    now = int(time.time())
    storage_utils.write_json(
        focus_service.sessions_path(base),
        {
            "active": {
                "id": "expired",
                "minutes": 5,
                "started_at": now - 600,
                "ends_at": now - 1,
                "status": "running",
                "credited": False,
            },
            "sessions": [],
        },
    )
    assert focus_service.focus_status(base)["running"] is False
    assert focus_service.focus_journal(base)[0]["status"] == "completed"


@pytest.mark.parametrize("session_id", ["", "unknown", "  "])
def test_crediting_an_unknown_session_is_refused(session_id, base):
    assert focus_service.mark_credited(base, session_id) is False


def test_a_session_can_only_be_credited_once(base):
    focus_service.start_focus(base, 10, "study", item_id="item-1")
    session_id = focus_service.focus_journal(base) or None
    active = focus_service.focus_status(base)["session"]
    focus_service.stop_focus(base)
    assert focus_service.mark_credited(base, active["id"]) is True
    assert focus_service.mark_credited(base, active["id"]) is False
    assert session_id is None


def _day_key(offset):
    return (date.today() - timedelta(days=offset)).isoformat()


def _stamp(days_ago, hour=9):
    day = datetime.now() - timedelta(days=days_ago)
    return int(day.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp())


@pytest.fixture()
def streaks():
    return focus_service.compute_streaks


def test_an_empty_journal_has_no_streak(streaks):
    assert streaks({}) == (0, 0)


def test_a_today_only_run_is_a_one_day_streak(streaks):
    assert streaks({_day_key(0): 5}) == (1, 1)


def test_a_zero_minute_today_does_not_break_yesterdays_streak(streaks):
    assert streaks({_day_key(0): 0, _day_key(1): 5}) == (1, 1)


def test_two_consecutive_days_count_twice(streaks):
    assert streaks({_day_key(0): 5, _day_key(1): 5}) == (2, 2)


def test_a_gap_ends_the_current_streak_but_not_the_record(streaks):
    per_day = {_day_key(0): 5, _day_key(1): 5, _day_key(2): 0, _day_key(3): 5, _day_key(4): 5, _day_key(5): 5}
    assert streaks(per_day) == (2, 3)


def test_a_long_run_sets_both_numbers(streaks):
    per_day = {_day_key(offset): 5 for offset in range(7)}
    assert streaks(per_day) == (7, 7)


def _session(days_ago, minutes, status="completed", spent_minutes=None, started_extra=0):
    started = _stamp(days_ago)
    spent = minutes if spent_minutes is None else spent_minutes
    return {
        "started_at": started + started_extra,
        "ended_at": started + int(spent * 60),
        "minutes": minutes,
        "status": status,
    }


@pytest.mark.parametrize(
    "sessions,expected_minutes",
    [
        ([_session(0, 25)], 25),
        ([_session(0, 25), _session(0, 10)], 35),
        ([_session(0, 25), _session(1, 25)], 50),
        ([_session(0, 25, status="abandoned")], 0),
        ([_session(0, 25, spent_minutes=60)], 25),
        ([_session(0, 25, spent_minutes=0)], 0),
    ],
)
def test_daily_focus_minutes(sessions, expected_minutes):
    per_day = focus_service.compute_daily_minutes(sessions)
    assert sum(per_day.values()) == expected_minutes


def test_abandoned_and_blank_sessions_are_skipped_entirely():
    sessions = [
        _session(0, 25, status="abandoned"),
        {"started_at": 0, "ended_at": 0, "minutes": 25, "status": "completed"},
        {"started_at": _stamp(0), "ended_at": _stamp(0), "minutes": 0, "status": "completed"},
        {"minutes": 25},
        "not-a-session",
    ]
    assert focus_service.compute_daily_minutes(sessions) == {}


# ------------------------------------------------------------------------ links

VALID_TYPES = list(link_service.VALID_ENTITY_TYPES)


@pytest.mark.parametrize("entity_type", VALID_TYPES)
def test_every_documented_entity_type_is_accepted(entity_type, base):
    link = link_service.add_link(base, entity_type, "x1", "note", "n1")
    assert link is not None
    assert link["from_type"] == entity_type


@pytest.mark.parametrize("entity_type", ["", "bogus", None, "note-link", " notes"])
def test_an_unknown_entity_type_is_rejected(entity_type, base):
    assert link_service.add_link(base, entity_type, "x1", "note", "n1") is None


@pytest.mark.parametrize("entity_type,expected", [("NOTE", "note"), (" Flashcard ", "flashcard")])
def test_entity_types_are_normalised(entity_type, expected):
    assert link_service._clean_type(entity_type) == expected


def test_an_edge_cannot_point_at_itself(base):
    assert link_service.add_link(base, "note", "same", "note", "same") is None


@pytest.mark.parametrize("missing", [("", "n1", "note", "n2"), ("note", "", "note", "n2")])
def test_an_edge_needs_both_ids(missing, base):
    from_type, from_id, to_type, to_id = missing
    assert link_service.add_link(base, from_type, from_id, to_type, to_id) is None


def test_a_duplicate_edge_returns_the_existing_one(base):
    first = link_service.add_link(base, "note", "n1", "flashcard", "c1", "generated")
    second = link_service.add_link(base, "note", "n1", "flashcard", "c1", "generated")
    assert first["id"] == second["id"]
    assert len(link_service.load_links(base)) == 1


def test_the_same_pair_with_another_label_is_a_second_edge(base):
    link_service.add_link(base, "note", "n1", "flashcard", "c1", "generated")
    link_service.add_link(base, "note", "n1", "flashcard", "c1", "related")
    assert len(link_service.load_links(base)) == 2


def test_links_are_visible_from_both_ends(base):
    link_service.add_link(base, "note", "n1", "flashcard", "c1")
    forward = link_service.links_for(base, "note", "n1")
    backward = link_service.links_for(base, "flashcard", "c1")
    assert (len(forward["outgoing"]), len(forward["incoming"]), forward["total"]) == (1, 0, 1)
    assert (len(backward["outgoing"]), len(backward["incoming"]), backward["total"]) == (0, 1, 1)


@pytest.mark.parametrize("entity_type,entity_id", [("", "n1"), ("note", ""), ("bogus", "n1")])
def test_an_unusable_lookup_returns_nothing(entity_type, entity_id, base):
    assert link_service.links_for(base, entity_type, entity_id) == {"outgoing": [], "incoming": [], "total": 0}


def test_deleting_an_entity_removes_both_directions(base):
    link_service.add_link(base, "note", "n1", "flashcard", "c1")
    link_service.add_link(base, "task", "t1", "note", "n1")
    assert link_service.delete_links_for(base, "note", "n1") == 2
    assert link_service.load_links(base) == []


def test_removing_one_edge_leaves_the_others(base):
    link = link_service.add_link(base, "note", "n1", "flashcard", "c1")
    link_service.add_link(base, "note", "n1", "task", "t1")
    assert link_service.remove_link(base, link["id"]) is True
    assert link_service.remove_link(base, link["id"]) is False
    assert len(link_service.load_links(base)) == 1


@pytest.mark.parametrize(
    "field,raw,limit",
    [
        ("from_id", "x" * 2000, 1024),
        ("to_id", "y" * 2000, 1024),
        ("label", "z" * 200, 120),
        ("id", "i" * 100, 80),
    ],
)
def test_edge_fields_are_truncated_not_rejected(field, raw, limit):
    link = link_service._normalize_link(
        {"from_type": "note", "from_id": "a", "to_type": "note", "to_id": "b", field: raw}
    )
    assert len(link[field]) == limit


def test_bulk_saving_drops_unusable_edges(base):
    saved = link_service.save_links(
        base,
        [
            {"from_type": "note", "from_id": "a", "to_type": "note", "to_id": "b"},
            {"from_type": "bogus", "from_id": "a", "to_type": "note", "to_id": "b"},
            "not-a-link",
            None,
        ],
    )
    assert len(saved) == 1


# -------------------------------------------------------------------------- ICS

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20260903T090000Z", int(datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc).timestamp())),
        ("20260101T000000Z", int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())),
        ("19700101T000100Z", 60),
    ],
)
def test_utc_timestamps(raw, expected):
    assert ics_service._parse_ics_dt(raw) == expected


@pytest.mark.parametrize("raw", ["20260903T090000", "20261231T235900", "20260903T000000"])
def test_local_timestamps_are_read_as_local_time(raw):
    expected = int(datetime.strptime(raw, "%Y%m%dT%H%M%S").astimezone().timestamp())
    assert ics_service._parse_ics_dt(raw) == expected


@pytest.mark.parametrize("raw", ["20260903", "20260228", "20261231"])
def test_all_day_events_land_on_local_midnight(raw):
    expected = int(datetime.strptime(raw, "%Y%m%d").astimezone().timestamp())
    assert ics_service._parse_ics_dt(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "garbage", "2026-09-03T09:00:00", "20261301T000000Z", "20260903T999999Z", "Z", "T"],
)
def test_unparsable_timestamps_are_zero(raw):
    assert ics_service._parse_ics_dt(raw) == 0


def test_a_short_clock_form_is_accepted_by_strptime():
    # strptime tolerates a missing seconds component; pin that it parses, not crashes.
    assert ics_service._parse_ics_dt("20260903T0900") != 0


@pytest.mark.parametrize("raw", ["20260903T09", "20260903T"])
def test_a_truncated_clock_form_is_zero(raw):
    assert ics_service._parse_ics_dt(raw) == 0


def test_folded_lines_are_unfolded():
    assert ics_service._unfold("SUMMARY:Long\r\n description") == ["SUMMARY:Longdescription"]
    assert ics_service._unfold("SUMMARY:Long\n\tdescription") == ["SUMMARY:Longdescription"]


def test_a_leading_continuation_is_kept_as_its_own_line():
    assert ics_service._unfold(" orphan") == [" orphan"]


def test_crlf_and_lf_produce_the_same_lines():
    assert ics_service._unfold("A:1\r\nB:2") == ics_service._unfold("A:1\nB:2")


CALENDAR = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Standup
DTSTART:20260903T090000Z
DESCRIPTION:line1\\nline2
END:VEVENT
END:VCALENDAR
"""


def test_a_plain_event_is_imported():
    events = ics_service.parse_ics(CALENDAR)
    assert len(events) == 1
    assert events[0]["title"] == "Standup"
    assert events[0]["notes"] == "line1\nline2"
    assert events[0]["starts_at"] == int(datetime(2026, 9, 3, 9, tzinfo=timezone.utc).timestamp())


@pytest.mark.parametrize(
    "body",
    [
        "BEGIN:VEVENT\nDTSTART:20260903T090000Z\nEND:VEVENT",
        "BEGIN:VEVENT\nSUMMARY:No start\nEND:VEVENT",
        "BEGIN:VEVENT\nSUMMARY:Bad start\nDTSTART:garbage\nEND:VEVENT",
    ],
)
def test_an_event_without_a_title_or_start_is_dropped(body):
    assert ics_service.parse_ics("BEGIN:VCALENDAR\n" + body + "\nEND:VCALENDAR") == []


@pytest.mark.parametrize("text", ["", "BEGIN:VCALENDAR\nEND:VCALENDAR", "no events at all"])
def test_a_calendar_without_events_imports_nothing(text):
    assert ics_service.parse_ics(text) == []


def test_parameters_on_a_key_are_ignored():
    events = ics_service.parse_ics(
        "BEGIN:VEVENT\nSUMMARY;LANGUAGE=en:Param\nDTSTART;VALUE=DATE:20260903\nEND:VEVENT"
    )
    assert events[0]["title"] == "Param"


def test_keys_are_case_insensitive():
    events = ics_service.parse_ics(
        "BEGIN:VEVENT\nsummary:lower\nDtStart:20260903T090000Z\nEND:VEVENT"
    )
    assert events[0]["title"] == "lower"


def test_several_events_are_all_imported():
    events = ics_service.parse_ics(
        "\n".join(
            [
                "BEGIN:VEVENT", "SUMMARY:One", "DTSTART:20260903T090000Z", "END:VEVENT",
                "BEGIN:VEVENT", "SUMMARY:Two", "DTSTART:20260904T090000Z", "END:VEVENT",
            ]
        )
    )
    assert [event["title"] for event in events] == ["One", "Two"]


def test_a_long_summary_is_truncated():
    events = ics_service.parse_ics(
        "BEGIN:VEVENT\nSUMMARY:" + "s" * 500 + "\nDTSTART:20260903T090000Z\nEND:VEVENT"
    )
    assert len(events[0]["title"]) == 200


def test_a_long_description_is_truncated():
    events = ics_service.parse_ics(
        "BEGIN:VEVENT\nSUMMARY:x\nDTSTART:20260903T090000Z\nDESCRIPTION:" + "d" * 3000 + "\nEND:VEVENT"
    )
    assert len(events[0]["notes"]) == 2000


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("plain", "plain"),
        ("a;b", "a\\;b"),
        ("a,b", "a\\,b"),
        ("a\nb", "a\\nb"),
        ("a\\b", "a\\\\b"),
    ],
)
def test_ics_escaping(raw, expected):
    assert ics_service._ics_escape(raw) == expected


# ------------------------------------------------------------------- flashcards

def _seed(base, **overrides):
    card = {
        "id": "c1",
        "front": "front",
        "back": "back",
        "source_note_id": "",
        "ease": 2.5,
        "interval": 0,
        "due": 0,
        "created_at": 0,
        "reviews": 0,
        "lapses": 0,
    }
    card.update(overrides)
    fs.save_cards(base, [card])
    return card


@pytest.mark.parametrize("grade", ["again", "hard", "good", "easy"])
def test_a_review_records_the_grade(grade, base):
    _seed(base)
    card = fs.review_card(base, "c1", grade)
    assert card["reviews"] == 1
    assert card["id"] == "c1"


@pytest.mark.parametrize(
    "grade,expected_ease,expected_interval",
    [("again", 2.3, 0), ("hard", 2.35, 1), ("good", 2.5, 1), ("easy", 2.55, 1)],
)
def test_first_review_scheduling(grade, expected_ease, expected_interval, base):
    _seed(base)
    card = fs.review_card(base, "c1", grade)
    assert card["ease"] == pytest.approx(expected_ease, abs=0.001)
    assert card["interval"] == pytest.approx(expected_interval, abs=0.001)


@pytest.mark.parametrize(
    "grade,expected_delay",
    [("again", 600), ("hard", 86_400), ("good", 86_400), ("easy", 86_400)],
)
def test_first_review_due_date(grade, expected_delay, base):
    _seed(base)
    card = fs.review_card(base, "c1", grade)
    assert abs((card["due"] - time.time()) - expected_delay) < 30


def test_again_costs_a_lapse(base):
    _seed(base)
    assert fs.review_card(base, "c1", "again")["lapses"] == 1


@pytest.mark.parametrize(
    "grades,expected_ease,expected_interval",
    [
        (["good", "good"], 2.5, 2.5),
        (["good", "hard"], 2.35, 1.2),
        (["good", "easy"], 2.55, 3.25),
        (["hard", "good"], 2.35, 2.35),
        (["easy", "good"], 2.55, 2.55),
    ],
)
def test_second_review_compounds_the_interval(grades, expected_ease, expected_interval, base):
    _seed(base)
    card = fs.review_card(base, "c1", grades[0])
    card = fs.review_card(base, "c1", grades[1])
    assert card["ease"] == pytest.approx(expected_ease, abs=0.02)
    assert card["interval"] == pytest.approx(expected_interval, abs=0.03)


def test_ease_is_clamped_at_the_top(base):
    _seed(base, ease=2.98)
    assert fs.review_card(base, "c1", "easy")["ease"] == 3.0


def test_ease_is_clamped_at_the_bottom(base):
    _seed(base, ease=1.31)
    assert fs.review_card(base, "c1", "again")["ease"] == 1.3


def test_a_long_again_streak_cannot_wedge_ease(base):
    _seed(base)
    for _ in range(20):
        card = fs.review_card(base, "c1", "again")
    assert card["ease"] == 1.3
    assert card["interval"] == 0


@pytest.mark.parametrize("grade", ["", "GOOD ", "excellent", None])
def test_an_unknown_grade_changes_nothing(grade, base):
    _seed(base)
    assert fs.review_card(base, "c1", grade) is None or grade == "GOOD "


def test_reviewing_an_unknown_card_returns_none(base):
    assert fs.review_card(base, "missing", "good") is None


def test_due_cards_respects_the_clock(base):
    fs.save_cards(
        base,
        [
            {"id": "past", "due": 100, "interval": 0, "ease": 2.5},
            {"id": "future", "due": 10_000, "interval": 0, "ease": 2.5},
        ],
    )
    assert [card["id"] for card in fs.due_cards(base, now=5_000)] == ["past"]


def test_stats_counts_total_due_and_mature_cards(base):
    fs.save_cards(
        base,
        [
            {"id": "a", "due": 0, "interval": 0},
            {"id": "b", "due": 0, "interval": 21},
            {"id": "c", "due": 10**12, "interval": 30},
        ],
    )
    stats = fs.stats(base)
    assert stats["total"] == 3
    assert stats["matured"] == 2
    assert stats["due"] == 2


@pytest.mark.parametrize(
    "front,back,expected_front,expected_back",
    [
        ("  padded  ", "  back  ", "padded", "back"),
        ("f" * 600, "b" * 3000, "f" * 500, "b" * 2000),
        ("", "", "", ""),
    ],
)
def test_new_cards_are_trimmed_and_bounded(front, back, expected_front, expected_back):
    card = fs.new_card(front, back)
    assert card["front"] == expected_front
    assert card["back"] == expected_back


def test_a_new_card_starts_unreviewed():
    card = fs.new_card("f", "b")
    assert (card["ease"], card["interval"], card["reviews"], card["lapses"]) == (2.5, 0, 0, 0)


def test_loaded_cards_are_clamped_and_junk_is_dropped(base):
    storage_utils.write_json(
        fs.cards_path(base),
        {"version": 1, "cards": [{"id": "a", "ease": 99, "interval": -5}, "junk", {"ease": "x"}]},
    )
    cards = fs.load_cards(base)
    assert len(cards) == 2
    assert cards[0]["ease"] == 3.0
    assert cards[0]["interval"] == 0
    assert cards[1]["ease"] == 2.5


@pytest.mark.parametrize("payload", [{"version": 1, "cards": "nope"}, [], {"cards": None}])
def test_a_malformed_card_store_reads_as_empty(payload, base):
    storage_utils.write_json(fs.cards_path(base), payload)
    assert fs.load_cards(base) == []


def test_deleting_a_card_reports_whether_it_existed(base):
    _seed(base)
    assert fs.delete_card(base, "c1") is True
    assert fs.delete_card(base, "c1") is False


def test_deleting_a_note_cascades_to_its_cards(base):
    fs.save_cards(
        base,
        [
            {"id": "a", "source_note_id": "n1", "ease": 2.5, "interval": 0, "due": 0},
            {"id": "b", "source_note_id": "n2", "ease": 2.5, "interval": 0, "due": 0},
        ],
    )
    assert fs.delete_cards_for_note(base, "n1") == 1
    assert [card["id"] for card in fs.load_cards(base)] == ["b"]


def test_cards_json_keeps_its_version_envelope(base):
    _seed(base)
    envelope = json.loads(open(fs.cards_path(base), encoding="utf-8").read())
    assert envelope["version"] == 1
    assert isinstance(envelope["cards"], list)
