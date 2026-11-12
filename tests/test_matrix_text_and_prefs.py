"""Matrix suite for pure text, time and preference helpers.

These are small functions, but they sit on user-visible surfaces (greeting, log
redaction, the Accept-Language header) where an off-by-one or an unescaped
newline is a real defect. Every bucket boundary and every rejected token shape
is enumerated instead of sampled.
"""
from __future__ import annotations

import re
import time

import pytest

from litebrowser.core import greetings, log, prefs, time_utils
from litebrowser.services import brief_service

# ------------------------------------------------------------------- greetings

PERIOD_BY_HOUR = {
    **{hour: "night" for hour in range(0, 5)},
    **{hour: "morning" for hour in range(5, 11)},
    11: "noon",
    **{hour: "afternoon" for hour in range(12, 18)},
    **{hour: "evening" for hour in range(18, 22)},
    **{hour: "night" for hour in range(22, 24)},
}


@pytest.mark.parametrize("hour,period", sorted(PERIOD_BY_HOUR.items()))
def test_every_hour_maps_to_one_cafe_period(hour, period):
    assert greetings.greeting_period(hour) == period


@pytest.mark.parametrize("hour", sorted(PERIOD_BY_HOUR))
def test_every_period_has_a_greeting_pair(hour):
    eyebrow, headline = greetings.cafe_greeting(hour)
    assert eyebrow and headline
    assert (eyebrow, headline) == greetings.CAFE_GREETINGS[greetings.greeting_period(hour)]


@pytest.mark.parametrize("hour", [0, 5, 11, 12, 18, 22])
def test_period_boundaries_are_half_open(hour):
    before = greetings.greeting_period(hour - 1) if hour else "night"
    assert greetings.greeting_period(hour) != before or hour in (0, 22)


def test_the_five_periods_are_the_only_greetings():
    assert set(greetings.CAFE_GREETINGS) == {"morning", "noon", "afternoon", "evening", "night"}
    assert {greetings.greeting_period(hour) for hour in range(24)} == set(greetings.CAFE_GREETINGS)


# ------------------------------------------------------------------- timestamps

@pytest.mark.parametrize("value", [0, None, "", False, []])
def test_an_empty_timestamp_renders_as_a_dash(value):
    assert time_utils.format_ts(value) == "-"


@pytest.mark.parametrize("value", [2**62, "not-a-number", object()])
def test_an_unusable_timestamp_renders_as_a_dash(value):
    assert time_utils.format_ts(value) == "-"


@pytest.mark.parametrize("stamp", [1, 86_400, 1_700_000_000, 1_800_000_000])
def test_a_real_timestamp_renders_in_local_time(stamp):
    rendered = time_utils.format_ts(stamp)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", rendered)
    if stamp > 0:
        assert rendered == time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


# -------------------------------------------------------------------- redaction

REDACTION_CASES = [
    ("Authorization: Bearer abc123def456", "abc123def456"),
    ("Bearer tokenvalue123", "tokenvalue123"),
    ("api_key=supersecret", "supersecret"),
    ("api-key: supersecret", "supersecret"),
    ("access_token=abcdef123456", "abcdef123456"),
    ("refresh_token=abcdef123456", "abcdef123456"),
    ("password=hunter2", "hunter2"),
    ("passwd: hunter2", "hunter2"),
    ("secret=topsecret", "topsecret"),
    ("token=zzz999", "zzz999"),
    ("https://user:pass@example.com/path", "user:pass"),
    ("sk-abcdefghijklmnopqrstuv", "sk-abcdefghijklmnopqrstuv"),
    ("ghp_abcdefghijklmnopqrst", "ghp_abcdefghijklmnopqrst"),
    ("ya29.abcdefghijklmnop", "ya29.abcdefghijklmnop"),
]


@pytest.mark.parametrize("text,secret", REDACTION_CASES)
def test_credential_shapes_are_masked(text, secret):
    cleaned = log.redact(text)
    assert secret not in cleaned
    assert "[redacted]" in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "plain words",
        "a path C:\\Users\\me\\notes.md",
        "https://example.com/?q=1",
        "no secrets here at all",
    ],
)
def test_ordinary_text_is_left_alone(text):
    assert log.redact(text) == text


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_redacts_to_empty(value):
    assert log.redact(value) == ""


# ----------------------------------------------------------------------- domains

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.example.com/a", "example.com"),
        ("https://example.com/a", "example.com"),
        ("https://WWW.Example.COM", "example.com"),
        ("http://sub.example.com:8080/x", "sub.example.com:8080"),
        ("ftp://files.example.com/x", "files.example.com"),
        ("https://www.example.com", "example.com"),
        ("", ""),
        ("nonsense", ""),
        ("file:///C:/x.html", ""),
        ("about:blank", ""),
    ],
)
def test_the_domain_of_a_url(url, expected):
    assert brief_service._domain(url) == expected


def test_top_domains_counts_and_orders():
    entries = [
        (1, "https://a.com/x"),
        (2, "https://www.a.com/y"),
        (3, "https://b.com/z"),
        (4, ""),
        (5, "nonsense"),
    ]
    assert brief_service.top_domains(entries) == [("a.com", 2), ("b.com", 1)]


def test_top_domains_honours_the_limit():
    entries = [(index, f"https://d{index}.com/") for index in range(10)]
    assert len(brief_service.top_domains(entries, limit=3)) == 3


@pytest.mark.parametrize("entries", [[], [(1, "")], [(1, "nonsense"), (2, "")]])
def test_top_domains_without_usable_entries_is_empty(entries):
    assert brief_service.top_domains(entries) == []


# ------------------------------------------------------------ accept-language

MESSY_LANGUAGE_CASES = [
    ("en-US", "en-US"),
    ("vi-VN,vi;q=0.9,en;q=0.8", "vi-VN,vi;q=0.9,en;q=0.8"),
    ("en;q=0.9", "en;q=0.9"),
    ("en;q=1", "en;q=1"),
    ("en;q=.5", "en;q=.5"),
    ("en;q=abc", "en"),
    ("en;q=", "en"),
    ("en;q=0.9;extra", "en"),
    (" en , fr ", "en,fr"),
    ("EN-us", "EN-us"),
    ("zh-Hant;q=0.8", "zh-Hant;q=0.8"),
    ("*", "*"),
    ("en-US-x-private", "en-US-x-private"),
    (",,,", ""),
    ("", ""),
    (None, ""),
    ("<script>alert(1)</script>", ""),
    ("en\r\nX-Evil: 1", ""),
    ("en\x00fr", ""),
    ("a" * 33, ""),
    ("a" * 32, "a" * 32),
]


@pytest.mark.parametrize("raw,expected", MESSY_LANGUAGE_CASES)
def test_accept_language_cleaning(raw, expected):
    assert prefs._clean_accept_language(raw) == expected


def test_a_newline_makes_the_header_value_unusable():
    assert prefs._clean_accept_language("en\nfr") == ""
    assert prefs._clean_accept_language("en\r\nX-Evil: 1") == ""
    assert prefs._clean_accept_language("en\x00fr") == ""


def test_at_most_twelve_entries_survive():
    raw = ",".join(["en", "fr", "de", "es", "it", "pt", "nl", "sv", "da", "fi", "no", "pl", "cs"])
    cleaned = prefs._clean_accept_language(raw)
    assert len(cleaned.split(",")) == 12
    assert "cs" not in cleaned


@pytest.mark.parametrize("raw", ["en-US", "vi-VN,vi;q=0.9,en;q=0.8", "fr;q=0.8", "de"])
def test_accept_language_round_trips_through_preferences(raw, tmp_path):
    base = str(tmp_path)
    prefs.set_accept_language(base, raw)
    assert prefs.get_accept_language(base) == raw


@pytest.mark.parametrize("raw", ["<script>", "en\r\nX-Evil: 1", "a" * 40, ""])
def test_an_unusable_value_clears_back_to_the_default(raw, tmp_path):
    base = str(tmp_path)
    prefs.set_accept_language(base, raw)
    assert prefs.get_accept_language(base) == prefs.DEFAULT_ACCEPT_LANGUAGE


def test_the_default_header_itself_survives_cleaning():
    assert prefs._clean_accept_language(prefs.DEFAULT_ACCEPT_LANGUAGE) == prefs.DEFAULT_ACCEPT_LANGUAGE
