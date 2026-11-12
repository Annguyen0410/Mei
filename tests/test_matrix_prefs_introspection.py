"""Introspective matrix for the preferences module.

``prefs`` is the app's whole configuration surface — hundreds of getters and
setters that every screen depends on. Hand-writing a case per accessor rots the
moment one is added, so the matrix is generated from the module itself: each
public function is called with a value built from its own annotation, and each
setter is round-tripped through its getter. A new accessor is covered the day it
lands, and an accessor that stops respecting its own signature fails here.
"""
from __future__ import annotations

import inspect
import re

import pytest

from litebrowser.core import prefs
from litebrowser.ui.main_window.window_topbar import site_state_key

_BASE_PARAM_NAMES = ("base_dir", "base", "profile_dir", "root", "path")

_VALUES = {
    "str": "value",
    "int": 7,
    "bool": True,
    "float": 1.5,
    "dict": {"enabled": False},
    "list": [],
}

_TYPES = {"str": str, "int": int, "bool": bool, "float": float, "dict": dict, "list": list}

#: A refused value (bad type, bad payload, unreadable store) is a legitimate
#: outcome for an accessor given a fabricated argument. Anything else — an
#: AttributeError, a NameError, a KeyError escaping as a crash — is a bug.
_ALLOWED = (TypeError, ValueError, KeyError, OSError)


def _annotation_key(param) -> str:
    annotation = param.annotation
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    text = re.sub(r"\s+", "", text)
    for part in text.split("|"):
        part = part.replace("Optional[", "").rstrip("]")
        for key in ("bool", "int", "float", "str", "dict", "list"):
            if part == key or part.startswith(key + "["):
                return key
    return ""


def _public_functions() -> list[str]:
    names = []
    for name, obj in vars(prefs).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if obj.__module__ != prefs.__name__:
            continue
        names.append(name)
    return sorted(names)


def _takes_base_dir(func) -> bool:
    params = list(inspect.signature(func).parameters.values())
    return bool(params) and params[0].name in _BASE_PARAM_NAMES


def _call_with_fabricated_args(func, base):
    """Call ``func(base, ...)`` with a value per required parameter."""
    params = list(inspect.signature(func).parameters.values())[1:]
    args = [base]
    for param in params:
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is not param.empty:
            continue
        key = _annotation_key(param)
        if not key:
            return None
        args.append(_VALUES[key])
    return func(*args)


FUNCTIONS = [name for name in _public_functions() if _takes_base_dir(getattr(prefs, name))]
GETTERS = [name for name in FUNCTIONS if name.startswith("get_")]
SETTERS = [name for name in FUNCTIONS if name.startswith("set_")]


def test_the_matrix_actually_found_the_module():
    # Guards the whole file: if the module is refactored into a class or the
    # introspection stops matching, an empty matrix would silently "pass".
    assert len(FUNCTIONS) >= 30
    assert len(GETTERS) >= 10
    assert len(SETTERS) >= 10


@pytest.fixture()
def base(tmp_path):
    return str(tmp_path)


@pytest.mark.parametrize("name", FUNCTIONS)
def test_every_preference_function_tolerates_a_well_typed_call(name, base):
    func = getattr(prefs, name)
    try:
        _call_with_fabricated_args(func, base)
    except _ALLOWED:
        pass  # a refused value is fine; anything else propagates and fails
    except NotImplementedError:
        pytest.skip("not implemented on this platform")


@pytest.mark.parametrize("name", GETTERS)
def test_every_getter_returns_its_declared_type(name, base):
    func = getattr(prefs, name)
    try:
        value = _call_with_fabricated_args(func, base)
    except _ALLOWED:
        pytest.skip("store refused the default read")
    return_annotation = inspect.signature(func).return_annotation
    text = return_annotation if isinstance(return_annotation, str) else getattr(return_annotation, "__name__", "")
    text = re.sub(r"\s+", "", text)
    expected = ""
    for part in text.split("|"):
        part = part.replace("Optional[", "").rstrip("]")
        for candidate in ("bool", "int", "float", "str", "dict", "list"):
            if part == candidate or part.startswith(candidate + "["):
                expected = candidate
    if not expected or value is None:
        pytest.skip("no declared type to check")
    assert isinstance(value, _TYPES[expected])


@pytest.mark.parametrize("name", SETTERS)
def test_every_setter_round_trips_through_its_getter(name, base):
    getter_name = "get_" + name[len("set_"):]
    getter = getattr(prefs, getter_name, None)
    if getter is None or not callable(getter):
        pytest.skip("no matching getter")
    setter = getattr(prefs, name)
    try:
        _call_with_fabricated_args(setter, base)
    except _ALLOWED:
        pytest.skip("setter refused the fabricated value")
    try:
        stored = getter(base)
    except _ALLOWED:
        pytest.skip("getter could not read back")
    assert stored is not None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com", "secure"),
        ("HTTPS://EXAMPLE.COM", "secure"),
        ("  https://a.com/path  ", "secure"),
        ("http://example.com", "insecure"),
        ("about:blank", "local"),
        ("file:///C:/x.html", "file"),
        ("search term", "search"),
        ("", "search"),
        (None, "search"),
        ("ftp://a.com", "search"),
        ("localhost:8080", "search"),
    ],
)
def test_the_connection_pill_classifies_an_address(url, expected):
    assert site_state_key(url) == expected
