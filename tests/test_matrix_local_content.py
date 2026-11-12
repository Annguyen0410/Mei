"""Matrix suite for the local-content gate: every ``file:`` shape it must judge.

The gate is the only thing standing between ``LocalContentCanAccessRemoteUrls``
and a downloaded page, so this file treats the URL grammar as hostile input: it
enumerates schemes, authorities, encodings, traversal, case variants, unicode
names and link escapes, and pins a decision for each.

Three historical holes are pinned here by name so they cannot come back:
network authorities were "not local, therefore allowed"; ``abspath`` let a
symlink or junction borrow the trust of the folder it appeared to sit in; and a
policy error fell through to the engine.
"""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from litebrowser.browser import local_content_policy as policy

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows path forms")


@pytest.fixture()
def sandbox(tmp_path):
    root = tmp_path / "web_support"
    (root / "Cục Quản Lý").mkdir(parents=True)
    (root / "index.html").write_text("<p>ok</p>", encoding="utf-8")
    (root / "Cục Quản Lý" / "index.html").write_text("<p>ok</p>", encoding="utf-8")
    (root / "dir with space").mkdir()
    (root / "dir with space" / "page.html").write_text("<p>ok</p>", encoding="utf-8")
    outside = tmp_path / "Downloads"
    outside.mkdir()
    (outside / "evil.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    return {"root": str(root), "outside": str(outside), "tmp": tmp_path}


# ---------------------------------------------------------------- scheme matrix

NON_FILE_URLS = [
    "https://example.com/",
    "https://example.com/a/b?c=d#e",
    "http://localhost:8080/",
    "http://127.0.0.1/",
    "about:blank",
    "about:config",
    "data:text/html,<h1>x</h1>",
    "javascript:void(0)",
    "blob:https://example.com/uuid",
    "chrome://settings",
    "ws://example.com/socket",
    "mailto:a@b.c",
    "",
    "not a url at all",
    "example.com",
]


@pytest.mark.parametrize("url", NON_FILE_URLS)
def test_non_file_schemes_are_never_gated(url):
    assert policy.is_file_url(url) is False
    assert policy.is_local_url(url) is False
    assert policy.navigation_decision(url, ("C:\\trusted",)) == policy.ALLOW


FILE_SCHEME_SPELLINGS = [
    "file:///C:/x.html",
    "FILE:///C:/x.html",
    "File:///C:/x.html",
    "fIlE:///C:/x.html",
    "  file:///C:/x.html  ",
]


@pytest.mark.parametrize("url", FILE_SCHEME_SPELLINGS)
def test_file_scheme_is_recognised_whatever_its_case(url):
    assert policy.is_file_url(url) is True


MALFORMED = ["file:", "file://", "file:////", "file://///", "file:?x=1", "file:#f"]


@pytest.mark.parametrize("url", MALFORMED)
def test_file_url_without_a_usable_path_is_blocked(url):
    assert policy.navigation_decision(url, ("C:\\trusted",)) == policy.BLOCK
    assert policy.navigation_decision(url, ("C:\\trusted",), True) == policy.BLOCK


# ------------------------------------------------------- authority / UNC matrix

NETWORK_AUTHORITIES = [
    "file://fileserver/share/x.html",
    "file://fileserver/C:/x.html",
    "file://192.168.1.10/share/x.html",
    "file://10.0.0.5/share/x.html",
    "file://nas.local/share/x.html",
    "file://fileserver",
    "file:////fileserver/share/x.html",
    "file://///fileserver/share/x.html",
    "file:///%2F%2Ffileserver/share/x.html",
    "file:///\\\\fileserver\\share\\x.html",
]


@pytest.mark.parametrize("url", NETWORK_AUTHORITIES)
def test_a_network_authority_is_never_local_content(url):
    assert policy.is_local_url(url) is False
    assert policy.is_trusted_local_url(url, ("C:\\trusted",)) is False


@pytest.mark.parametrize("url", NETWORK_AUTHORITIES)
def test_a_network_authority_is_blocked_by_default(url):
    assert policy.navigation_decision(url, ("C:\\trusted",)) == policy.BLOCK


@pytest.mark.parametrize("url", NETWORK_AUTHORITIES)
def test_the_untrusted_opt_in_cannot_unlock_a_network_share(url):
    # The opt-in is about *provenance*, not about dialling SMB on the user's behalf.
    assert policy.navigation_decision(url, ("C:\\trusted",), True) == policy.BLOCK


def test_localhost_authority_is_a_local_file():
    assert policy.is_local_url("file://localhost/C:/x.html") is True
    assert policy.is_local_url("file://LOCALHOST/C:/x.html") is True


@WINDOWS
def test_drive_letter_authority_is_a_local_file():
    # RFC 8089's file://C:/path form; local, so the roots decide, not the parser.
    assert policy.is_local_url("file://C:/Users/me/page.html") is True
    assert policy.local_path("file://C:/Users/me/page.html").lower().startswith("c:")


# ------------------------------------------------------------- path shape matrix

@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/a/b.html",
        "file://localhost/C:/a/b.html",
        "file:///C:/a/b%20c.html",
        "file:///C:/a/%E1%BB%A9ng.html",
        "file:///C:/a/b.html?query=1",
        "file:///C:/a/b.html#frag",
    ],
)
@WINDOWS
def test_windows_file_urls_map_to_a_path(url):
    path = policy.local_path(url)
    assert path
    assert not path.startswith("/")
    assert "?" not in path and "#" not in path


@WINDOWS
def test_percent_encoding_is_decoded_before_comparison():
    assert policy.local_path("file:///C:/a/b%20c.html") == "C:/a/b c.html"


@WINDOWS
def test_unicode_paths_survive_the_round_trip():
    path = policy.local_path("file:///C:/a/%E1%BB%A9ng%20t%E1%BB%A7.html")
    assert path == "C:/a/ứng tủ.html"


@WINDOWS
def test_encoded_backslash_is_treated_as_a_separator():
    # %5C decodes to a backslash; it must not smuggle a UNC path past the check.
    assert policy.local_path("file:///C:/a%5C..%5C..%5Cx.html") == "C:/a\\..\\..\\x.html"


# ------------------------------------------------------------- decision matrix

def _url(base, *parts):
    return pathlib.Path(base, *parts).as_uri()


DECISION_CASES = [
    # (kind of target, inside roots?, opt-in, expected)
    ("inside", True, False, policy.ALLOW),
    ("inside", True, True, policy.ALLOW),
    ("nested", True, False, policy.ALLOW),
    ("outside", False, False, policy.BLOCK),
    ("outside", False, True, policy.ALLOW),
    ("sibling_prefix", False, False, policy.BLOCK),
    ("parent", False, False, policy.BLOCK),
    ("traversal", False, False, policy.BLOCK),
]


def _target(kind, sandbox):
    root, outside = sandbox["root"], sandbox["outside"]
    if kind == "inside":
        return _url(root, "index.html")
    if kind == "nested":
        return _url(root, "Cục Quản Lý", "index.html")
    if kind == "outside":
        return _url(outside, "evil.html")
    if kind == "sibling_prefix":
        return _url(sandbox["tmp"], "web_support_old", "index.html")
    if kind == "parent":
        return _url(root, "..", "web_support_evil", "x.html")
    if kind == "traversal":
        return str(pathlib.Path(_url(root, "index.html")).as_posix()).replace(
            "/index.html", "/../Downloads/evil.html"
        )
    raise AssertionError(kind)


@pytest.mark.parametrize("kind,_,opt_in,expected", DECISION_CASES)
def test_decision_matrix(kind, _, opt_in, expected, sandbox):
    assert policy.navigation_decision(_target(kind, sandbox), (sandbox["root"],), opt_in) == expected


@pytest.mark.parametrize("kind,inside,opt_in,expected", DECISION_CASES)
def test_decision_matrix_with_no_trusted_roots(kind, inside, opt_in, expected, sandbox):
    # With no roots every local file is untrusted, so only the explicit opt-in
    # lets one load — there is no folder left that could be trusted by accident.
    want = policy.ALLOW if opt_in else policy.BLOCK
    assert policy.navigation_decision(_target(kind, sandbox), (), opt_in) == want


def test_the_drive_root_is_local_but_untrusted():
    # "file:///" is the root of the current drive: a real local path, so the
    # opt-in covers it, but nothing about it is trusted by default.
    assert policy.is_local_url("file:///") is True
    assert policy.navigation_decision("file:///", ("C:\\trusted",)) == policy.BLOCK


@pytest.mark.parametrize(
    "root_kind",
    ["plain", "trailing_sep", "uppercased", "duplicated", "with_empty", "relative_dot"],
)
def test_root_normalisation_does_not_change_the_answer(root_kind, sandbox):
    root = sandbox["root"]
    roots = {
        "plain": (root,),
        "trailing_sep": (root + os.sep,),
        "uppercased": (root.upper(),),
        "duplicated": (root, root),
        "with_empty": ("", None, root),
        "relative_dot": (os.path.join(root, "."),),
    }[root_kind]
    if root_kind == "uppercased" and os.name != "nt":
        pytest.skip("case-insensitive filesystem only")
    assert policy.navigation_decision(_url(root, "index.html"), roots) == policy.ALLOW


@pytest.mark.parametrize("bad_root", ["", None, "\0bad", "/no/such/root/anywhere"])
def test_an_unusable_root_is_skipped_not_fatal(bad_root):
    roots = policy.trusted_local_roots(None, (bad_root,))
    assert isinstance(roots, tuple)


def test_sibling_folder_with_a_trusted_prefix_is_not_trusted(sandbox):
    sibling = _url(sandbox["tmp"], "web_support_old", "index.html")
    assert policy.navigation_decision(sibling, (sandbox["root"],)) == policy.BLOCK


def test_a_file_named_like_the_root_is_not_the_root(sandbox):
    same_name = _url(sandbox["tmp"], "other", "web_support")
    assert policy.navigation_decision(same_name, (sandbox["root"],)) == policy.BLOCK


def test_traversal_back_out_of_the_root_is_blocked(sandbox):
    traversed = _url(sandbox["root"], "..", "Downloads", "evil.html")
    assert policy.navigation_decision(traversed, (sandbox["root"],)) == policy.BLOCK


def test_percent_encoded_traversal_is_blocked(sandbox):
    uri = _url(sandbox["root"], "index.html").replace("index.html", "%2e%2e/Downloads/evil.html")
    assert policy.navigation_decision(uri, (sandbox["root"],)) == policy.BLOCK


def test_extra_root_from_the_window_is_honoured(sandbox):
    uri = _url(sandbox["outside"], "evil.html")
    assert policy.navigation_decision(uri, (sandbox["root"], sandbox["outside"])) == policy.ALLOW


def test_query_string_does_not_turn_a_trusted_page_into_an_untrusted_one(sandbox):
    uri = _url(sandbox["root"], "index.html") + "?tab=2"
    assert policy.navigation_decision(uri, (sandbox["root"],)) == policy.ALLOW


# --------------------------------------------------------------- link escapes

def _symlink_or_skip(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_symlink_inside_the_root_cannot_escape_it(sandbox):
    link = os.path.join(sandbox["root"], "innocent.html")
    _symlink_or_skip(os.path.join(sandbox["outside"], "evil.html"), link)
    assert policy.navigation_decision(pathlib.Path(link).as_uri(), (sandbox["root"],)) == policy.BLOCK


def test_symlinked_directory_inside_the_root_cannot_escape_it(sandbox):
    link = os.path.join(sandbox["root"], "linked_dir")
    _symlink_or_skip(sandbox["outside"], link)
    assert policy.navigation_decision(pathlib.Path(link, "evil.html").as_uri(), (sandbox["root"],)) == policy.BLOCK


def test_symlink_pointing_inside_the_root_stays_allowed(sandbox):
    link = os.path.join(sandbox["root"], "alias.html")
    _symlink_or_skip(os.path.join(sandbox["root"], "index.html"), link)
    assert policy.navigation_decision(pathlib.Path(link).as_uri(), (sandbox["root"],)) == policy.ALLOW


@WINDOWS
def test_junction_inside_the_root_cannot_escape_it(sandbox):
    link = os.path.join(sandbox["root"], "junction")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", link, sandbox["outside"]],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J unavailable: {(result.stderr or '').strip()}")
    assert policy.navigation_decision(pathlib.Path(link, "evil.html").as_uri(), (sandbox["root"],)) == policy.BLOCK


# ------------------------------------------------------------- unicode + spaces

def test_unicode_folder_inside_the_root_is_allowed(sandbox):
    assert policy.navigation_decision(_url(sandbox["root"], "Cục Quản Lý", "index.html"), (sandbox["root"],)) == policy.ALLOW


def test_folder_with_a_space_inside_the_root_is_allowed(sandbox):
    assert policy.navigation_decision(_url(sandbox["root"], "dir with space", "page.html"), (sandbox["root"],)) == policy.ALLOW


def test_unicode_name_outside_the_root_is_blocked(sandbox):
    assert policy.navigation_decision(_url(sandbox["outside"], "Cục Quản Lý.html"), (sandbox["root"],)) == policy.BLOCK
