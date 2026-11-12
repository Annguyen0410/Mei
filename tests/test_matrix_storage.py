"""Matrix suite for storage safety: path containment and atomic JSON writes.

Two properties keep a profile recoverable: an untrusted relative path can never
resolve outside its root, and a store that failed to parse is preserved instead
of being overwritten with a default. Both are exercised here against traversal,
Windows path forms, corrupt bytes and unserialisable payloads.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from litebrowser.core import storage_utils


@pytest.fixture()
def root(tmp_path):
    target = tmp_path / "profile"
    (target / "notes").mkdir(parents=True)
    (target / "notes" / "a.md").write_text("a", encoding="utf-8")
    (target / "Cục Quản Lý").mkdir()
    return target


# -------------------------------------------------------------- safe_child_path

ACCEPTED_CHILDREN = [
    "a.md",
    "notes/a.md",
    "notes\\a.md",
    "dir with space/file.txt",
    "Cục Quản Lý/ghi chú.md",
    "deep/er/still/file.json",
]


@pytest.mark.parametrize("relative", ACCEPTED_CHILDREN)
def test_an_ordinary_relative_path_resolves_under_the_root(relative, root):
    resolved = storage_utils.safe_child_path(str(root), relative)
    assert resolved
    assert os.path.normcase(resolved).startswith(os.path.normcase(os.path.realpath(str(root))))
    assert resolve_tail(relative) in os.path.normcase(resolved)


def resolve_tail(relative):
    return os.path.normcase(relative.replace("\\", "/")).split("/")[-1]


REJECTED_CHILDREN = [
    "",
    ".",
    "..",
    "../escape.txt",
    "../../escape.txt",
    "notes/../../escape.txt",
    "notes/..",
    "notes/./a.md",
    "notes//a.md",
    "notes/a.md/",
    "/absolute.txt",
    "\\absolute.txt",
    "C:/windows/system32/x.txt",
    "C:relative.txt",
    "a:b.txt",
    "bad\x00name.txt",
    "..\\..\\escape.txt",
    "notes\\..\\..\\escape.txt",
]


@pytest.mark.parametrize("relative", REJECTED_CHILDREN)
def test_a_traversing_or_absolute_path_is_refused(relative, root):
    assert storage_utils.safe_child_path(str(root), relative) == ""


@pytest.mark.parametrize("relative", [None, 5, b"bytes", ["a"], {"a": 1}])
def test_a_non_string_child_is_refused(relative, root):
    assert storage_utils.safe_child_path(str(root), relative) == ""


def test_a_symlinked_child_cannot_escape_the_root(root, tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    assert storage_utils.safe_child_path(str(root), "link.txt") == ""


def test_a_symlinked_directory_cannot_escape_the_root(root, tmp_path):
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "x.txt").write_text("secret", encoding="utf-8")
    link = root / "linked"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    assert storage_utils.safe_child_path(str(root), "linked/x.txt") == ""


# ------------------------------------------------------------------- JSON store

def test_a_written_store_reads_back_unchanged(tmp_path):
    path = str(tmp_path / "store.json")
    payload = {"version": 2, "rows": [{"id": "a", "text": "ứng"}], "flag": True}
    storage_utils.write_json(path, payload)
    assert storage_utils.read_json(path, None) == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"a": 1},
        [1, 2, 3],
        "text",
        42,
        None,
        {"nested": {"deep": {"deeper": [1, {"x": "y"}]}}},
        {"unicode": "Cục Quản Lý — 日本語 — emoji 🎴"},
    ],
)
def test_any_json_payload_round_trips(payload, tmp_path):
    path = str(tmp_path / "x.json")
    storage_utils.write_json(path, payload)
    assert storage_utils.read_json(path, "MISSING") == payload


def test_a_missing_store_returns_the_caller_default(tmp_path):
    assert storage_utils.read_json(str(tmp_path / "absent.json"), {"default": True}) == {"default": True}


def test_writing_creates_missing_parent_folders(tmp_path):
    path = str(tmp_path / "deep" / "er" / "store.json")
    storage_utils.write_json(path, {"ok": 1})
    assert pathlib.Path(path).is_file()


def test_a_corrupt_store_is_preserved_and_then_write_protected(tmp_path):
    path = tmp_path / "store.json"
    path.write_bytes(b'{"broken": ')
    before = path.read_bytes()

    assert storage_utils.read_json(str(path), {"default": True}) == {"default": True}
    preserved = list(tmp_path.glob(".store.json.corrupt-*.bak"))
    assert preserved, "the damaged bytes must be preserved next to the store"
    assert preserved[0].read_bytes() == before

    with pytest.raises(storage_utils.CorruptionWriteError):
        storage_utils.write_json(str(path), {"replacement": True})
    assert path.read_bytes() == before


def test_an_explicit_repair_may_replace_a_preserved_store(tmp_path):
    path = tmp_path / "store.json"
    path.write_bytes(b"not json at all")
    storage_utils.read_json(str(path), {})
    storage_utils.write_json(str(path), {"repaired": True}, allow_replace_corrupt=True)
    assert storage_utils.read_json(str(path), {}) == {"repaired": True}


def test_an_empty_file_counts_as_damaged(tmp_path):
    path = tmp_path / "empty.json"
    path.write_bytes(b"")
    with pytest.raises(storage_utils.CorruptionWriteError):
        storage_utils.write_json(str(path), {"x": 1})


def test_an_unserialisable_payload_keeps_the_previous_file(tmp_path):
    path = tmp_path / "store.json"
    storage_utils.write_json(path, {"keep": "me"})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        storage_utils.write_json(str(path), {"bad": float("nan")})
    assert path.read_bytes() == before


def test_a_successful_read_clears_the_damage_mark(tmp_path):
    path = tmp_path / "store.json"
    path.write_bytes(b"{broken")
    storage_utils.read_json(str(path), {})
    key = os.path.normcase(os.path.abspath(path))
    assert key in storage_utils.damaged_paths()

    path.write_bytes(json.dumps({"fixed": True}).encode("utf-8"))
    assert storage_utils.read_json(str(path), {}) == {"fixed": True}
    assert key not in storage_utils.damaged_paths()


def test_write_text_atomic_replaces_the_file(tmp_path):
    path = tmp_path / "note.md"
    storage_utils.write_text_atomic(str(path), "first")
    storage_utils.write_text_atomic(str(path), "second — ứng")
    assert path.read_text(encoding="utf-8") == "second — ứng"


def test_write_text_atomic_leaves_no_temporary_files(tmp_path):
    storage_utils.write_text_atomic(str(tmp_path / "note.md"), "body")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


@pytest.mark.parametrize("name", ["file", "a b", "ứng.txt", "x" * 60, ""])
def test_temporary_names_are_private_and_unique(name, tmp_path):
    seen = set()
    for _ in range(3):
        fd, path = storage_utils.tempfile_mkstemp_same_dir(str(tmp_path), name)
        os.close(fd)
        assert os.path.basename(path).startswith(".")
        assert path not in seen
        seen.add(path)
