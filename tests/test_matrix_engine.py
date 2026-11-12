"""Matrix suite for the engine: security-version table and diagnostics report.

The engine is the product's biggest security dependency, and two numbers decide
whether a build is honest: the Chromium base and Qt's backported security
version. These tables pin both, plus the diagnostics page that reports them, so
a "green" build cannot quietly mean an unpatched engine or an invented version.
"""
from __future__ import annotations

import pytest

from litebrowser.core import engine_security, product
from litebrowser.services import engine_diagnostics

KNOWN_VERSIONS = {
    "6.11.0": (140, 146),
    "6.11.1": (140, 148),
    "6.11.2": (140, 151),
    "6.11.3": (140, 155),
}


@pytest.mark.parametrize("version,expected", sorted(KNOWN_VERSIONS.items()))
def test_known_runtimes_report_base_and_security_version(version, expected):
    assert engine_security.known_engine(version) == expected
    assert engine_security.security_version_for(version) == expected[1]


@pytest.mark.parametrize("version,expected", sorted(KNOWN_VERSIONS.items()))
def test_every_known_runtime_shares_the_611_chromium_base(version, expected):
    assert expected[0] == engine_security.CHROMIUM_BASE == 140


@pytest.mark.parametrize("version,security", [("6.11.0", 146), ("6.11.3", 155)])
def test_a_known_runtime_meets_the_shipped_floor(version, security):
    assert engine_security.meets_floor(security)
    assert engine_security.meets_floor(security, engine_security.MIN_SECURITY_VERSION)


@pytest.mark.parametrize("raw", [" 6.11.0 ", "\t6.11.2\n", "6.11.3 "])
def test_surrounding_whitespace_does_not_change_the_lookup(raw):
    assert engine_security.known_engine(raw) is not None


@pytest.mark.parametrize("unknown", ["6.11.4", "6.12.0", "5.15.2", "", None, "9.9.9", "six.eleven"])
def test_an_unknown_runtime_is_unknown_not_a_guess(unknown):
    assert engine_security.known_engine(unknown) is None
    assert engine_security.security_version_for(unknown) is None
    assert engine_security.meets_floor(engine_security.security_version_for(unknown)) is False


@pytest.mark.parametrize(
    "security,floor,expected",
    [
        (146, 146, True),
        (147, 146, True),
        (155, 146, True),
        (145, 146, False),
        (0, 146, False),
        (None, 146, False),
        ("146", "146", True),
        ("155", 146, True),
        ("not-a-number", 146, False),
        (146, "not-a-number", False),
        ("146.5", 146, False),
    ],
)
def test_meets_floor_table(security, floor, expected):
    assert engine_security.meets_floor(security, floor) is expected


def test_the_floor_is_not_below_the_oldest_shippable_runtime():
    # 6.11.0 is the oldest runtime the pinned wheel can resolve to (146).
    assert engine_security.MIN_SECURITY_VERSION >= KNOWN_VERSIONS["6.11.0"][1]


# ------------------------------------------------------------ chromium parsing

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("140.0.7339.225", 140),
        ("140", 140),
        ("087.0.4280.141", 87),
        (" 140.0", 140),
        ("", 0),
        (None, 0),
        ("abc", 0),
        ("v140.0", 0),
        ("-1.0", -1),
        ("140.", 140),
    ],
)
def test_chromium_major_table(raw, expected):
    assert engine_diagnostics.chromium_major(raw) == expected


# --------------------------------------------------------------- sandbox status

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_sandbox_opt_out_is_reported_as_insecure(value):
    status = engine_diagnostics.sandbox_status({engine_diagnostics.ENV_SANDBOX_OFF: value})
    assert "Disabled" in status
    assert "insecure" in status


@pytest.mark.parametrize("value", ["0", "false", "", "off", "no", "maybe"])
def test_sandbox_is_unknown_when_it_cannot_be_proven(value):
    status = engine_diagnostics.sandbox_status({engine_diagnostics.ENV_SANDBOX_OFF: value})
    assert status == engine_diagnostics.UNKNOWN


def test_sandbox_is_unknown_without_the_variable():
    assert engine_diagnostics.sandbox_status({}) == engine_diagnostics.UNKNOWN


# ---------------------------------------------------- hardware acceleration

@pytest.mark.parametrize(
    "flags,needle",
    [
        ("--disable-gpu", "Disabled by QTWEBENGINE_CHROMIUM_FLAGS"),
        ("--disable-gpu --foo", "Disabled by QTWEBENGINE_CHROMIUM_FLAGS"),
        ("--foo --disable-gpu", "Disabled by QTWEBENGINE_CHROMIUM_FLAGS"),
        ("--disable-software-rasterizer", "Software rasterizer disabled"),
        ("--foo --disable-software-rasterizer", "Software rasterizer disabled"),
        ("--foo=--disable-gpu-elsewhere", "Disabled by QTWEBENGINE_CHROMIUM_FLAGS"),
    ],
)
def test_acceleration_flags_are_reported(flags, needle):
    status = engine_diagnostics.hardware_acceleration_status({engine_diagnostics.ENV_CHROMIUM_FLAGS: flags})
    assert needle in status


@pytest.mark.parametrize("flags", ["", "--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11"])
def test_acceleration_is_unknown_without_a_disable_flag(flags):
    status = engine_diagnostics.hardware_acceleration_status({engine_diagnostics.ENV_CHROMIUM_FLAGS: flags})
    assert status == engine_diagnostics.UNKNOWN


# ------------------------------------------------------------- report assembly

def _facts(**overrides):
    facts = {
        "binding": "PyQt6",
        "qt": "6.11.0",
        "qtwebengine": "6.11.0",
        "chromium": "140.0.7339.225",
        "gpu_backend": "auto",
        "profile": "default",
        "user_agent": "Mozilla/5.0",
    }
    facts.update(overrides)
    return facts


def test_a_current_engine_reports_no_warnings():
    report = engine_diagnostics.collect(_facts(), environ={})
    assert report["Warnings"] == []
    assert report["Chromium security version"] == "146"
    assert report["Chromium major"] == "140"
    assert report["Chromium security patch"] == "140.0.7339.225"
    assert report["Mei version"] == product.APP_VERSION


@pytest.mark.parametrize(
    "key",
    [
        "Mei version",
        "Python",
        "Executable",
        "Platform",
        "PyQt binding",
        "Qt",
        "QtWebEngine",
        "Chromium",
        "Chromium major",
        "Chromium security patch",
        "Chromium security version",
        "GPU backend",
        "Hardware acceleration",
        "Sandbox",
        "Active profile",
        "User-Agent",
        "Warnings",
    ],
)
def test_report_always_carries_every_documented_fact(key):
    assert key in engine_diagnostics.collect(_facts(), environ={})


@pytest.mark.parametrize("missing", ["", None, "   "])
def test_an_unreadable_chromium_version_is_a_warning(missing):
    report = engine_diagnostics.collect(_facts(chromium=missing), environ={})
    assert report["Chromium major"] == engine_diagnostics.UNKNOWN
    assert report["Chromium security patch"] == engine_diagnostics.UNKNOWN
    assert any("could not be read" in warn for warn in report["Warnings"])


@pytest.mark.parametrize("chromium", ["87.0.4280.141", "100.0.4896.60", "119.0.0.0"])
def test_an_old_chromium_base_is_a_warning(chromium):
    report = engine_diagnostics.collect(_facts(chromium=chromium), environ={})
    assert any("below the supported floor" in warn for warn in report["Warnings"])


@pytest.mark.parametrize("chromium", ["120.0.0.0", "140", "141.0.0.1"])
def test_a_supported_or_unparsable_major_is_not_an_old_engine_warning(chromium):
    report = engine_diagnostics.collect(_facts(chromium=chromium), environ={})
    assert not any("below the supported floor" in warn for warn in report["Warnings"])


@pytest.mark.parametrize("webengine", ["9.9.9", "", None])
def test_an_unknown_webengine_patch_level_is_a_warning(webengine):
    report = engine_diagnostics.collect(_facts(qtwebengine=webengine), environ={})
    assert report["Chromium security version"] == engine_diagnostics.UNKNOWN
    assert any("unknown" in warn.lower() for warn in report["Warnings"])


def test_the_legacy_pyqt5_path_is_called_out():
    report = engine_diagnostics.collect(_facts(binding="PyQt5", chromium="87.0.4280.141"), environ={})
    assert any("LEGACY" in warn for warn in report["Warnings"])


def test_pyqt5_does_not_also_get_the_patch_level_warning():
    warnings = engine_diagnostics.collect(_facts(binding="PyQt5", qtwebengine="5.15.2"), environ={})["Warnings"]
    assert not any("security patch level" in warn for warn in warnings)


def test_a_disabled_sandbox_is_a_warning():
    report = engine_diagnostics.collect(
        _facts(), environ={engine_diagnostics.ENV_SANDBOX_OFF: "1"}
    )
    assert any("sandbox is disabled" in warn for warn in report["Warnings"])


def test_a_lower_but_known_patch_level_is_reported_against_the_floor(monkeypatch):
    # Pretend the floor moved past 6.11.0: the build must say so, not pass silently.
    monkeypatch.setattr(engine_security, "MIN_SECURITY_VERSION", 155)
    report = engine_diagnostics.collect(_facts(), environ={})
    assert any("below the required" in warn for warn in report["Warnings"])


def test_missing_facts_render_as_unknown_not_empty():
    report = engine_diagnostics.collect({}, environ={})
    for key in ("PyQt binding", "Qt", "QtWebEngine", "Chromium", "GPU backend", "Active profile"):
        assert report[key] == engine_diagnostics.UNKNOWN


def test_format_report_lists_every_fact_and_the_warning_section():
    text = engine_diagnostics.format_report(engine_diagnostics.collect(_facts(), environ={}))
    assert "Mei version:" in text
    assert "Chromium security version: 146" in text
    assert "Warnings: none" in text


def test_format_report_renders_warnings_as_bullets():
    report = engine_diagnostics.collect(_facts(binding="PyQt5", chromium="87.0"), environ={})
    text = engine_diagnostics.format_report(report)
    assert "Warnings:" in text
    assert "\u2022 " in text


@pytest.mark.parametrize("empty", [None, {}])
def test_format_report_without_facts_says_so(empty):
    assert engine_diagnostics.format_report(empty) == "No engine facts available."
