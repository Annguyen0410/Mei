"""Matrix suite for four services that touch user data without a UI.

Agent actions, the download log, the feed reader and userscript matching were the
least-covered non-UI modules in the app. Each is deterministic once its inputs
are controlled, so the hostile and boundary shapes are enumerated here instead of
left to whatever a manual session happens to pass in.
"""
from __future__ import annotations

import urllib.error

import pytest

from litebrowser.browser import extension_patterns
from litebrowser.core import prefs
from litebrowser.services import (
    agent_actions,
    download_mgr,
    life_service,
    personal_service,
    rss_service,
)


@pytest.fixture()
def base(tmp_path):
    return str(tmp_path)


# ----------------------------------------------------------------- agent actions

@pytest.mark.parametrize(
    "tabs",
    [
        [],
        [{"url": "not-a-url", "title": "x"}],
        [{"title": "no url"}],
        [{"url": "about:blank", "title": "blank"}],
        [{}],
    ],
)
def test_tabs_without_pages_are_reported_as_nothing_to_summarise(tabs, base):
    assert agent_actions.summarize_tabs(tabs, base) == "# Tab Summary\n\nNo tabs to summarize."


def test_tabs_are_grouped_by_domain_when_no_ai_is_configured(base, monkeypatch):
    monkeypatch.setattr(agent_actions, "_ai_answer", lambda *_a, **_k: "")
    tabs = [
        {"url": "https://a.com/1", "title": "One"},
        {"url": "https://a.com/2", "title": "Two"},
        {"url": "https://b.com/3", "title": "Three"},
    ]
    digest = agent_actions.summarize_tabs(tabs, base)
    assert digest.startswith("# Tab Summary — 3 tabs")
    assert "## a.com" in digest and "## b.com" in digest
    assert "- One" in digest and "- Two" in digest


def test_only_http_tabs_are_counted(base, monkeypatch):
    monkeypatch.setattr(agent_actions, "_ai_answer", lambda *_a, **_k: "")
    digest = agent_actions.summarize_tabs(
        [{"url": "https://a.com/x", "title": "kept"}, {"url": "file:///C:/x", "title": "dropped"}],
        base,
    )
    assert "1 tabs" in digest
    assert "dropped" not in digest


def test_an_ai_answer_is_used_verbatim(base, monkeypatch):
    monkeypatch.setattr(agent_actions, "_ai_answer", lambda *_a, **_k: "grouped by topic")
    assert agent_actions.summarize_tabs([{"url": "https://a.com", "title": "t"}], base) == (
        "# Tab Summary\n\ngrouped by topic"
    )


@pytest.mark.parametrize(
    "answer,expected",
    [("", ""), ("No related items found", ""), ("  padded answer  ", "padded answer")],
)
def test_an_unusable_ai_answer_falls_back(answer, expected, base, monkeypatch):
    monkeypatch.setattr(
        "litebrowser.services.ai_service.answer_query", lambda *_a, **_k: {"answer": answer}
    )
    monkeypatch.setattr(prefs, "load_ai_settings", lambda _b: {"provider": "openrouter"})
    assert agent_actions._ai_answer(base, "prompt") == expected


def test_a_provider_failure_is_not_fatal(base, monkeypatch):
    monkeypatch.setattr(prefs, "load_ai_settings", lambda _b: {"provider": "ollama"})
    monkeypatch.setattr(
        "litebrowser.services.ai_service.answer_query",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")),
    )
    assert agent_actions._ai_answer(base, "prompt") == ""


def test_the_default_provider_is_treated_as_offline(base, monkeypatch):
    monkeypatch.setattr(prefs, "load_ai_settings", lambda _b: {"provider": "rag"})
    assert agent_actions._ai_answer(base, "prompt") == ""


def test_unreadable_ai_settings_are_not_fatal(base, monkeypatch):
    monkeypatch.setattr(
        prefs, "load_ai_settings", lambda _b: (_ for _ in ()).throw(ValueError("bad json"))
    )
    assert agent_actions._ai_answer(base, "prompt") == ""


@pytest.mark.parametrize(
    "text,expected_count",
    [
        ("", 0),
        ("   ", 0),
        ("abc", 0),
        ("- buy milk", 1),
        ("- buy milk; call mom|file taxes", 3),
        ("http://example.com\nsee the page", 1),
        ("# heading\n! alert\nreal task here", 1),
        ("✓ done thing\n• second thing", 2),
    ],
)
def test_tasks_are_extracted_from_free_text(text, expected_count, base):
    assert len(agent_actions.extract_tasks_from_text(base, text)) == expected_count


def test_extracted_tasks_land_in_the_ai_bucket(base):
    created = agent_actions.extract_tasks_from_text(base, "write the report")
    assert created[0]["title"] == "write the report"
    assert created[0]["bucket"] == "ai"


def test_a_very_long_line_is_truncated_to_a_task_title(base):
    created = agent_actions.extract_tasks_from_text(base, "x" * 400)
    assert len(created[0]["title"]) == 140


def test_a_quiet_week_says_so(base, monkeypatch):
    monkeypatch.setattr(prefs, "load_history_entries", lambda _b: [])
    monkeypatch.setattr(life_service, "load_tasks", lambda _b: [])
    monkeypatch.setattr(personal_service, "list_notes", lambda _b: [])
    review = agent_actions.weekly_review(base)
    assert "Weekly Review" in review
    assert "A quiet week" in review


def test_a_busy_week_reports_counts_and_days(base, monkeypatch):
    import time

    now = int(time.time())
    monkeypatch.setattr(
        prefs, "load_history_entries", lambda _b: [(now, "https://a.com/x"), (now, "file:///x")]
    )
    monkeypatch.setattr(
        life_service,
        "load_tasks",
        lambda _b: [{"title": "shipped", "completed": True, "updated_at": now}],
    )
    monkeypatch.setattr(personal_service, "list_notes", lambda _b: [{"id": "n1"}])
    review = agent_actions.weekly_review(base)
    assert "**Pages visited this week**: 2" in review
    assert "Tasks completed**: 1" in review
    assert "Notes in vault**: 1" in review
    assert "## Completed tasks" in review


def test_a_tab_digest_can_be_saved_as_a_note(base, monkeypatch):
    monkeypatch.setattr(agent_actions, "_ai_answer", lambda *_a, **_k: "")
    monkeypatch.setattr(
        personal_service, "create_note", lambda b, title, body, category="": {"title": title, "body": body, "category": category}
    )
    note = agent_actions.summarize_tabs_to_note(base, [{"url": "https://a.com", "title": "T"}], "My digest")
    assert note["title"] == "My digest"
    assert note["category"] == "AI"
    assert note["body"].startswith("# Tab Summary")


# --------------------------------------------------------------------- downloads

def test_a_download_gets_a_stable_increasing_id(base):
    first = download_mgr.add_download(base, "https://a.com/f", "/tmp/f.bin")
    second = download_mgr.add_download(base, "https://a.com/g", "/tmp/g.bin")
    assert (first, second) == (1, 2)


def test_ids_grow_while_rows_remain(base):
    ids = [download_mgr.add_download(base, f"https://a.com/{index}", "/tmp/f.bin") for index in range(3)]
    assert ids == [1, 2, 3]


def test_a_removed_newest_id_is_reused(base):
    """Characterisation of a known limit, not an endorsement.

    The next id is ``max(existing) + 1``, so deleting the newest row lets the next
    download take that id back. A late completion signal for the deleted download
    would then update the new row — the residual of the v6.4 index-collision bug,
    which the id scheme narrowed but did not close. Pinned here so a fix (a
    persisted counter) visibly changes this test rather than sliding in unnoticed.
    """
    first = download_mgr.add_download(base, "https://a.com/f", "/tmp/f.bin")
    download_mgr.remove_download(base, first)
    assert download_mgr.add_download(base, "https://a.com/g", "/tmp/g.bin") == first


def test_a_status_update_targets_the_right_entry(base):
    first = download_mgr.add_download(base, "https://a.com/f", "/tmp/f.bin")
    download_mgr.add_download(base, "https://a.com/g", "/tmp/g.bin")
    assert download_mgr.update_status(base, first, "done") is True
    rows = download_mgr.load_list(base)
    assert rows[0]["status"] == "done"
    assert rows[1]["status"] == "downloading"


@pytest.mark.parametrize("download_id", [0, 99, -1])
def test_updating_an_unknown_download_reports_failure(download_id, base):
    download_mgr.add_download(base, "https://a.com/f", "/tmp/f.bin")
    assert download_mgr.update_status(base, download_id, "done") is False


def test_removing_an_unknown_download_reports_failure(base):
    assert download_mgr.remove_download(base, 42) is False


def test_the_filename_defaults_to_the_basename(base):
    download_mgr.add_download(base, "https://a.com/f", "/tmp/report.pdf")
    assert download_mgr.load_list(base)[0]["filename"] == "report.pdf"


def test_a_malformed_download_store_reads_as_empty(base, monkeypatch):
    monkeypatch.setattr(prefs, "downloads_list_path", lambda _b: str(base) + "/dl.json")
    with open(str(base) + "/dl.json", "w", encoding="utf-8") as handle:
        handle.write('{"not": "a list"}')
    assert download_mgr.load_list(base) == []


# --------------------------------------------------------------------------- RSS

RSS2 = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>First</title><link>https://a.com/1</link><description>&lt;p&gt;Hello&lt;/p&gt;</description></item>
  <item><title>Second</title><link>https://a.com/2</link><description>Plain</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom one</title><link href="https://b.com/1"/><summary>Sum</summary></entry>
</feed>"""


def test_rss2_items_are_parsed():
    items = rss_service._parse_entries(RSS2)
    assert [item["title"] for item in items] == ["First", "Second"]
    assert items[0]["url"] == "https://a.com/1"


def test_html_is_stripped_from_the_summary():
    assert rss_service._parse_entries(RSS2)[0]["summary"] == "Hello"


def test_atom_entries_are_parsed():
    items = rss_service._parse_entries(ATOM)
    assert items == [{"title": "Atom one", "url": "https://b.com/1", "summary": "Sum"}]


@pytest.mark.parametrize("payload", [b"", b"not xml", b"<rss><channel>", b"<html><body>x</body></html>"])
def test_unparsable_feeds_produce_nothing(payload):
    assert rss_service._parse_entries(payload) == []


def test_the_item_limit_is_honoured():
    assert len(rss_service._parse_entries(RSS2, limit=1)) == 1


def test_an_item_without_a_title_is_skipped():
    payload = b"<rss><channel><item><link>https://a.com</link></item></channel></rss>"
    assert rss_service._parse_entries(payload) == []


def test_long_titles_and_summaries_are_bounded():
    payload = (
        b"<rss><channel><item><title>" + b"t" * 400 + b"</title><link>https://a.com</link>"
        b"<description>" + b"d" * 900 + b"</description></item></channel></rss>"
    )
    item = rss_service._parse_entries(payload)[0]
    assert len(item["title"]) == 200
    assert len(item["summary"]) == 300


@pytest.mark.parametrize("url,title,expected_title", [
    ("https://a.com/feed", "", "https://a.com/feed"),
    ("https://a.com/feed", "My feed", "My feed"),
    ("https://a.com/" + "x" * 200, "", ("https://a.com/" + "x" * 200)[:100]),
])
def test_adding_a_feed_defaults_its_title(url, title, expected_title, base):
    feed = rss_service.add_feed(base, url, title)
    assert feed["title"] == expected_title
    assert feed["items"] == []


def test_adding_the_same_feed_twice_returns_the_first(base):
    first = rss_service.add_feed(base, "https://a.com/feed")
    second = rss_service.add_feed(base, "https://a.com/feed", "other")
    assert first["title"] == second["title"]
    assert len(rss_service.load_feeds(base)) == 1


def test_removing_a_feed_reports_whether_it_existed(base):
    rss_service.add_feed(base, "https://a.com/feed")
    assert rss_service.remove_feed(base, "https://a.com/feed") is True
    assert rss_service.remove_feed(base, "https://a.com/feed") is False


@pytest.mark.parametrize("payload", [{"feeds": "nope"}, [], {"feeds": [1, "x", {"url": "u"}]}])
def test_a_malformed_feed_store_reads_as_the_valid_entries(payload, base, monkeypatch):
    monkeypatch.setattr(rss_service, "_path", lambda _b: str(base) + "/feeds.json")
    import json

    with open(str(base) + "/feeds.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    feeds = rss_service.load_feeds(base)
    assert all(isinstance(feed, dict) for feed in feeds)


def test_refreshing_an_unknown_feed_says_so(base):
    assert rss_service.refresh_feed(base, "https://nope/feed") == (0, "feed not found")


def test_a_fresh_feed_is_served_from_the_store(base, monkeypatch):
    import time

    rss_service.add_feed(base, "https://a.com/feed")
    feeds = rss_service.load_feeds(base)
    feeds[0]["items"] = [{"title": "cached"}]
    feeds[0]["fetched_at"] = int(time.time())
    rss_service.save_feeds(base, feeds)

    monkeypatch.setattr(
        rss_service, "_fetch", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fetched a fresh feed"))
    )
    assert rss_service.refresh_feed(base, "https://a.com/feed") == (1, "")


def test_a_successful_refresh_stores_its_items(base, monkeypatch):
    rss_service.add_feed(base, "https://a.com/feed")
    monkeypatch.setattr(rss_service, "_fetch", lambda *_a, **_k: RSS2)
    assert rss_service.refresh_feed(base, "https://a.com/feed") == (2, "")
    assert len(rss_service.load_feeds(base)[0]["items"]) == 2


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError("offline"), OSError("reset"), ValueError("bad")],
)
def test_a_failed_refresh_returns_the_error_and_keeps_the_store(error, base, monkeypatch):
    rss_service.add_feed(base, "https://a.com/feed")
    monkeypatch.setattr(
        rss_service, "_fetch", lambda *_a, **_k: (_ for _ in ()).throw(error)
    )
    count, message = rss_service.refresh_feed(base, "https://a.com/feed")
    assert count == 0
    assert message
    assert rss_service.load_feeds(base)[0]["items"] == []


# --------------------------------------------------------------- userscript match

SCRIPT = """
// ==UserScript==
// @name        My tweak
// @match       https://example.com/*
// @match       https://*.example.org/docs/*
// @exclude     https://example.com/private/*
// ==/UserScript==
console.log("body");
"""


def test_metadata_is_parsed_from_the_header():
    matches, excludes, name = extension_patterns.parse_user_script_metadata(SCRIPT)
    assert name == "My tweak"
    assert matches == ["https://example.com/*", "https://*.example.org/docs/*"]
    assert excludes == ["https://example.com/private/*"]


@pytest.mark.parametrize(
    "source",
    [
        "",
        "console.log(1);",
        "// @match https://example.com/*",
        "// ==UserScript==\n// ==/UserScript==",
    ],
)
def test_a_script_without_metadata_has_no_matches(source):
    matches, excludes, name = extension_patterns.parse_user_script_metadata(source)
    assert (matches, excludes, name) == ([], [], "")


def test_lines_outside_the_block_are_ignored():
    source = "// @match https://a.com/*\n// ==UserScript==\n// ==/UserScript==\n// @match https://b.com/*"
    matches, _excludes, _name = extension_patterns.parse_user_script_metadata(source)
    assert matches == []


@pytest.mark.parametrize(
    "url,pattern,expected",
    [
        ("https://example.com/x", "https://example.com/*", True),
        ("https://example.com/", "https://example.com/*", True),
        ("https://example.com/a/b", "https://example.com/a/*", True),
        ("https://example.com/b", "https://example.com/a/*", False),
        ("http://example.com/x", "https://example.com/*", False),
        ("https://other.com/x", "https://example.com/*", False),
        ("https://sub.example.com/x", "https://*.example.com/*", True),
        ("https://example.com/x", "https://*.example.com/*", True),
        ("https://a.b.example.com/x", "https://*.example.com/*", True),
        ("https://notexample.com/x", "https://*.example.com/*", False),
        ("https://example.com/x", "*://example.com/*", True),
        ("https://anything.test/x", "*://*/*", True),
        ("https://example.com", "https://example.com", True),
        ("https://example.com/x", "https://example.com", True),
        ("https://example.com/x", "no-scheme-here", False),
    ],
)
def test_url_pattern_matching(url, pattern, expected):
    assert extension_patterns.url_matches_pattern(url, pattern) is expected


def test_no_match_rules_means_every_page():
    assert extension_patterns.script_matches("https://anything.test/x", [], []) is True


def test_a_match_rule_limits_the_script():
    assert extension_patterns.script_matches("https://example.com/x", ["https://example.com/*"], []) is True
    assert extension_patterns.script_matches("https://other.com/x", ["https://example.com/*"], []) is False


def test_an_exclude_rule_wins_over_a_match():
    assert (
        extension_patterns.script_matches(
            "https://example.com/private/x", ["https://example.com/*"], ["https://example.com/private/*"]
        )
        is False
    )


def test_the_shipped_script_header_matches_its_own_example():
    matches, excludes, name = extension_patterns.parse_user_script_metadata(SCRIPT)
    assert name
    assert extension_patterns.script_matches("https://example.com/public/x", matches, excludes) is True
    assert extension_patterns.script_matches("https://example.com/private/x", matches, excludes) is False
