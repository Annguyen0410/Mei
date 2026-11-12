"""Matrix suite for the theme engine: contrast, accents and every palette.

The interface is painted from colour tokens, so a palette is only correct when
its text actually carries contrast on its own surfaces. The code enforces a few
of those relationships while resolving a palette; this file holds it to them for
**every** theme × accent pair rather than the handful a screenshot review covers.
"""
from __future__ import annotations

import re

import pytest

from litebrowser.core import theme_data

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

COLOR_KEYS = (
    "MAIN_BG",
    "MAIN_BG_ALT",
    "CARD_BG",
    "SIDEBAR_BG",
    "BORDER_SOFT",
    "TEXT",
    "TEXT_MUTED",
    "ACCENT",
    "ACCENT_HOVER",
    "ACCENT_SOFT",
    "INPUT_BG",
    "INPUT_FOCUS",
    "DANGER",
    "SUCCESS",
    "CLAY",
    "WARNING",
    "RULE",
    "RULE_STRONG",
    "ACCENT_WASH",
    "ACCENT_QUIET",
    "SURFACE",
    "SURFACE_ALT",
    "SURFACE_SUNK",
    "EDITOR_BG",
    "NAV_BG",
    "FOCUS_RING",
    "SELECT_BG",
    "SELECT_FG",
    "ON_WARM",
    "TEXT_ON_ACCENT",
    "TEXT_ON_DANGER",
    "ACCENT_FILL_HOVER",
    "TEXT_DIM",
)

MODES = sorted(theme_data.PALETTES)
ACCENTS = sorted(theme_data.ACCENTS)
HEX_ACCENT = "#7a5cff"


# ---------------------------------------------------------------------- contrast

@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("#ffffff", "#000000", 21.0),
        ("#000000", "#ffffff", 21.0),
        ("#ffffff", "#ffffff", 1.0),
        ("#000000", "#000000", 1.0),
        ("#171a1c", "#171a1c", 1.0),
        ("#808080", "#ffffff", 3.95),
    ],
)
def test_contrast_ratio_landmarks(first, second, expected):
    assert theme_data.contrast_ratio(first, second) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize("first,second", [("#123456", "#abcdef"), ("#000000", "#808080"), ("#ff0000", "#00ff00")])
def test_contrast_ratio_is_symmetric(first, second):
    assert theme_data.contrast_ratio(first, second) == pytest.approx(
        theme_data.contrast_ratio(second, first)
    )


@pytest.mark.parametrize(
    "color,expected",
    [
        ("#ffffff", True),
        ("#f5f5f5", True),
        ("#a0a0a0", True),
        ("#808080", False),
        ("#000000", False),
        ("#171a1c", False),
        ("", False),
        ("zzz", False),
    ],
)
def test_light_surface_detection(color, expected):
    assert theme_data._is_light_color(color) is expected


@pytest.mark.parametrize(
    "foreground,background,amount,expected",
    [
        ("#ffffff", "#000000", 0.0, "#000000"),
        ("#ffffff", "#000000", 1.0, "#ffffff"),
        ("#ffffff", "#000000", 0.5, "#808080"),
        ("#000000", "#ffffff", 1.0, "#000000"),
    ],
)
def test_blending_hits_its_endpoints(foreground, background, amount, expected):
    assert theme_data._blend_hex(foreground, background, amount) == expected


@pytest.mark.parametrize("amount", [0.1, 0.25, 0.5, 0.75, 0.9])
def test_blending_always_returns_a_six_digit_hex(amount):
    assert HEX.match(theme_data._blend_hex("#123456", "#abcdef", amount))


# ------------------------------------------------------------------------ accents

@pytest.mark.parametrize("accent", ACCENTS)
def test_every_preset_name_is_a_valid_accent(accent):
    assert theme_data.valid_accent(accent) is True


@pytest.mark.parametrize("accent", ["#aabbcc", "#AABBCC", "#000000", "#ffffff", HEX_ACCENT])
def test_a_six_digit_hex_is_a_valid_accent(accent):
    assert theme_data.valid_accent(accent) is True


@pytest.mark.parametrize("accent", ["#abc", "#aabbccdd", "", "nope", "AABBCC", "#gggggg", None, 5, ["#aabbcc"]])
def test_anything_else_is_not_a_valid_accent(accent):
    assert theme_data.valid_accent(accent) is False


def test_the_accent_controls_exactly_the_documented_tokens():
    assert theme_data.accent_keys() == ("ACCENT", "ACCENT_HOVER", "ACCENT_SOFT", "INPUT_FOCUS")


# ------------------------------------------------------------------ day / night

DAY_NIGHT_PAIRS = [
    ("minimal", "minimal-night"),
    ("latte", "cafe-night"),
    ("rose-day", "midnight-ember"),
    ("dawn", "cafe-night"),
    ("matcha-day", "forest-night"),
    ("sand-day", "ocean-night"),
    ("lavender-day", "lavender-night"),
    ("cocoa-day", "mocha-mint"),
    ("rain-day", "rain-night"),
    ("sunrise-day", "midnight-ember"),
    ("autumn-day", "cafe-night"),
]


@pytest.mark.parametrize("day,night", DAY_NIGHT_PAIRS)
def test_automatic_day_night_switching(day, night):
    assert theme_data.theme_variant(day, dark=False) == day
    assert theme_data.theme_variant(night, dark=True) == night
    assert theme_data.theme_variant(day, dark=True) == night


@pytest.mark.parametrize("night", ["cafe-night", "midnight-ember"])
def test_a_shared_night_theme_resolves_to_its_first_day_family(night):
    # Several day themes share one night palette (dawn/latte/autumn -> cafe-night),
    # so night -> day resolves to the first family rather than being undefined.
    assert theme_data.theme_variant(night, dark=False) in theme_data.PALETTES


@pytest.mark.parametrize("mode", ["zzz", "", "not-a-theme"])
def test_an_unknown_theme_falls_back_to_the_documented_default(mode):
    assert theme_data.theme_variant(mode, dark=False) == theme_data.DEFAULT_THEME
    assert theme_data.theme_variant(mode, dark=True) == "minimal-night"


# ------------------------------------------------------- every mode × every accent

@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_every_palette_pair_resolves_to_complete_tokens(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    missing = [key for key in COLOR_KEYS if key not in tokens]
    assert not missing, f"{mode}/{accent} is missing {missing}"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_every_colour_token_is_a_hex_colour(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    bad = {key: tokens.get(key) for key in COLOR_KEYS if not HEX.match(str(tokens.get(key)))}
    assert not bad


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_filled_buttons_stay_readable_in_every_palette(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    assert theme_data.contrast_ratio(tokens["TEXT_ON_ACCENT"], tokens["ACCENT"]) >= 4.5


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_muted_text_stays_readable_on_the_editor_surface(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    assert theme_data.contrast_ratio(tokens["TEXT_MUTED"], tokens["INPUT_BG"]) >= 4.5


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_hover_state_stays_readable_on_the_accent_wash(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    assert theme_data.contrast_ratio(tokens["ACCENT_HOVER"], tokens["ACCENT_SOFT"]) >= 4.5


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("accent", [None, "brass", HEX_ACCENT])
def test_clay_reads_as_text_on_the_canvas(mode, accent):
    tokens = theme_data.palette_tokens(mode, accent)
    assert theme_data.contrast_ratio(tokens["CLAY"], tokens["MAIN_BG"]) >= 4.5


@pytest.mark.parametrize("mode", MODES)
def test_night_detection_follows_the_surface_not_the_name(mode):
    tokens = theme_data.palette_tokens(mode)
    assert theme_data.is_night_theme(mode) is (not theme_data._is_light_color(tokens["MAIN_BG"]))


@pytest.mark.parametrize("accent", ACCENTS)
def test_every_named_accent_resolves_on_a_light_and_a_night_palette(accent):
    for mode in ("minimal", "minimal-night"):
        tokens = theme_data.palette_tokens(mode, accent)
        assert theme_data.contrast_ratio(tokens["TEXT_ON_ACCENT"], tokens["ACCENT"]) >= 4.5
        assert HEX.match(tokens["ACCENT"])


@pytest.mark.parametrize("mode", MODES)
def test_an_explicit_accent_replaces_the_palette_default(mode):
    plain = theme_data.palette_tokens(mode)
    overridden = theme_data.palette_tokens(mode, HEX_ACCENT)
    assert overridden["ACCENT_BASE"].lower() == HEX_ACCENT
    assert plain["ACCENT_BASE"] != overridden["ACCENT_BASE"] or plain["ACCENT"].lower() != HEX_ACCENT


@pytest.mark.parametrize("mode", MODES)
def test_the_selected_accent_is_recorded_before_night_adjustment(mode):
    tokens = theme_data.palette_tokens(mode, "#123456")
    assert tokens["ACCENT_BASE"] == "#123456"


@pytest.mark.parametrize("mode", MODES)
def test_semantic_surfaces_point_at_the_palette_they_describe(mode):
    tokens = theme_data.palette_tokens(mode)
    assert tokens["SURFACE"] == tokens["CARD_BG"]
    assert tokens["SURFACE_ALT"] == tokens["MAIN_BG_ALT"]
    assert tokens["NAV_BG"] == tokens["SIDEBAR_BG"]
    assert tokens["RULE"] == tokens["BORDER_SOFT"]
    assert tokens["FOCUS_RING"] == tokens["INPUT_FOCUS"]
    assert tokens["SELECT_FG"] == tokens["TEXT"]
