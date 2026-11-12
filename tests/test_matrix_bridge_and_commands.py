"""Matrix suite for the phone bridge's untrusted input and the command registry.

The bridge is reachable from the LAN and from an extension, so every string that
reaches it is attacker-controlled: the pairing code, the Authorization header and
the JSON payload. Each parser is enumerated against malformed, oversized and
hostile shapes. The command registry is checked for the invariants its surfaces
autocomplete from.
"""
from __future__ import annotations

import pytest

from litebrowser.core import commands
from litebrowser.services import android_bridge_service as bridge

PREFIX = bridge.PAIRING_PREFIX
VALID_TOKEN = "a" * 24


def code(host="192.168.1.5", port="8765", token=VALID_TOKEN, prefix=PREFIX):
    return f"{prefix}|{host}|{port}|{token}"


# --------------------------------------------------------------- pairing codes

@pytest.mark.parametrize(
    "host",
    ["192.168.1.5", "10.0.0.2", "nas.local", "mei-box", "127.0.0.1", "host-name.example.com"],
)
def test_a_well_formed_code_is_accepted(host):
    parsed = bridge.parse_pairing_code(code(host=host))
    assert parsed == {"host": host, "port": "8765", "token": VALID_TOKEN}


@pytest.mark.parametrize("port", ["1", "80", "8765", "65535", "0080"])
def test_valid_ports_are_accepted(port):
    assert bridge.parse_pairing_code(code(port=port))["port"] == port


@pytest.mark.parametrize("port", ["0", "65536", "999999", "", "abc", "80a", "-1", "80.5"])
def test_invalid_ports_are_refused(port):
    assert bridge.parse_pairing_code(code(port=port)) is None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "MEI2|192.168.1.5|8765|token",
        "MEI1|192.168.1.5|8765",
        "MEI1|192.168.1.5|8765|token|extra",
        "MEI1||8765|token",
        "MEI1|192.168.1.5||token",
        "MEI1|192.168.1.5|8765|",
        "MEI1|192.168.1.5|8765|" + "t" * (bridge.PAIRING_MAX_TOKEN_CHARS + 1),
        "MEI1|bad host|8765|token",
        "MEI1|http://x|8765|token",
        "MEI1|" + "h" * 254 + "|8765|token",
        "MEI1|192.168.1.5|8765|tok\nen",
        "MEI1|192.168.1.5|8765|tok\x00en",
        None,
        12345,
    ],
)
def test_malformed_codes_are_refused(raw):
    assert bridge.parse_pairing_code(raw) is None


def test_surrounding_whitespace_is_tolerated():
    parsed = bridge.parse_pairing_code("  " + code(host=" 192.168.1.5 ", port=" 8765 ", token=" tok ") + "  ")
    assert parsed == {"host": "192.168.1.5", "port": "8765", "token": "tok"}


@pytest.mark.parametrize("host", ["::1", "[::1]", "fe80::1", "[fe80::1]"])
def test_ipv6_hosts_are_accepted(host):
    parsed = bridge.parse_pairing_code(code(host=host))
    assert parsed is not None
    assert parsed["host"] == host


@pytest.mark.parametrize("raw", ["MEI1|::gg|8765|token", "MEI1|:x:y:|8765|token"])
def test_a_broken_ipv6_host_is_refused(raw):
    assert bridge.parse_pairing_code(raw) is None


def test_a_short_hex_group_host_is_accepted_as_ipv6_shorthand():
    # The parser accepts any lowercase-hex group form; it bounds shape, not validity.
    assert bridge.parse_pairing_code("MEI1|1:2:3:4:5|8765|token") is not None


def test_the_token_length_limit_is_inclusive():
    limit = bridge.PAIRING_MAX_TOKEN_CHARS
    assert bridge.parse_pairing_code(code(token="t" * limit)) is not None
    assert bridge.parse_pairing_code(code(token="t" * (limit + 1))) is None


# ----------------------------------------------------------------- bearer header

@pytest.mark.parametrize(
    "header,expected",
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),
        ("BEARER abc123", "abc123"),
        ("Bearer   abc123  ", "abc123"),
        ("Bearer token-with.dots_and-dashes", "token-with.dots_and-dashes"),
    ],
)
def test_a_bearer_header_is_parsed(header, expected):
    assert bridge._parse_bearer(header) == expected


@pytest.mark.parametrize(
    "header", [None, "", "   ", "Bearer", "Bearer ", "Token abc", "Basic abc", "abc123", "Bearer}\t"]
)
def test_anything_else_is_not_a_bearer_header(header):
    assert bridge._parse_bearer(header) is None


# ------------------------------------------------------------------ payload safety

SAFE_PAYLOADS = [
    None,
    True,
    False,
    0,
    1,
    -1,
    10**18,
    1.5,
    "",
    "short text",
    [],
    [1, 2, 3],
    {},
    {"a": 1},
    {"nested": {"list": [1, {"deep": "value"}]}},
]


@pytest.mark.parametrize("payload", SAFE_PAYLOADS)
def test_ordinary_payloads_are_safe(payload):
    assert bridge._payload_is_safe(payload) is True


UNSAFE_PAYLOADS = [
    float("inf"),
    float("nan"),
    b"bytes",
    object(),
    {"key": object()},
]


@pytest.mark.parametrize("payload", UNSAFE_PAYLOADS)
def test_unrepresentable_values_are_unsafe(payload):
    assert bridge._payload_is_safe(payload) is False


def test_a_string_at_the_field_limit_is_safe():
    limit = bridge.MAX_FIELD_CHARS
    assert bridge._payload_is_safe("x" * limit) is True
    assert bridge._payload_is_safe("x" * (limit + 1)) is False


def test_deep_nesting_is_bounded():
    value = "leaf"
    for _ in range(20):
        value = {"k": value}
    assert bridge._payload_is_safe(value) is True
    assert bridge._payload_is_safe({"k": value}) is False


def test_wide_dicts_are_bounded():
    assert bridge._payload_is_safe({str(index): 1 for index in range(128)}) is True
    assert bridge._payload_is_safe({str(index): 1 for index in range(129)}) is False


def test_long_lists_are_bounded():
    assert bridge._payload_is_safe([1] * 256) is True
    assert bridge._payload_is_safe([1] * 257) is False


def test_non_string_keys_are_unsafe():
    assert bridge._payload_is_safe({1: "value"}) is False


def test_overlong_keys_are_unsafe():
    assert bridge._payload_is_safe({"k" * 129: "value"}) is False


# --------------------------------------------------------------- command registry

def test_command_names_are_unique():
    names = commands.command_names()
    assert len(names) == len(set(names))


@pytest.mark.parametrize("name", commands.command_names())
def test_every_command_is_slash_prefixed_and_lowercase(name):
    assert name.startswith("/")
    assert name == name.lower()
    assert " " not in name


@pytest.mark.parametrize("name", commands.command_names())
def test_by_name_round_trips(name):
    command = commands.by_name(name)
    assert command is not None
    assert command.name == name


@pytest.mark.parametrize("name", ["", "/nope", "home", "/HOME", None])
def test_by_name_refuses_anything_unknown(name):
    assert commands.by_name(name) is None


@pytest.mark.parametrize("command", commands.COMMANDS, ids=lambda c: c.name)
def test_completion_offers_a_space_only_when_an_argument_is_expected(command):
    assert command.completion() == command.name + (" " if command.takes_arg else "")


@pytest.mark.parametrize("command", commands.COMMANDS, ids=lambda c: c.name)
def test_hint_appends_the_example_when_there_is_one(command):
    if command.example:
        assert command.hint() == f"{command.description} · {command.example}"
    else:
        assert command.hint() == command.description


@pytest.mark.parametrize("command", commands.COMMANDS, ids=lambda c: c.name)
def test_every_command_declares_a_known_kind(command):
    assert command.kind in ("action", "nav")
    assert command.description.strip()


@pytest.mark.parametrize("command", commands.COMMANDS, ids=lambda c: c.name)
def test_a_documented_example_is_valid_usage_for_that_command(command):
    # `example` is optional, but when it is there it must show this command.
    if command.example:
        assert command.example.startswith(command.name)


def test_completions_and_hints_cover_exactly_the_registry():
    assert commands.completions() == [command.completion() for command in commands.COMMANDS]
    assert set(commands.hints()) == set(commands.command_names())


def test_nav_and_action_names_partition_the_registry():
    nav = set(commands.nav_names())
    action = set(commands.action_names())
    assert not nav & action
    assert nav | action == set(commands.command_names())


def test_navigation_commands_come_before_actions():
    kinds = [command.kind for command in commands.COMMANDS]
    assert kinds == sorted(kinds, key=lambda kind: 0 if kind == "nav" else 1)
