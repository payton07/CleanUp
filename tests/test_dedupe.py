"""Duplicate detection and resolution tests."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.dedupe import apply_dedupe, file_hash, find_duplicates


def test_find_duplicates_groups_identical_content(tmp_path: Path):
    (tmp_path / "a.txt").write_text("same content")
    (tmp_path / "b.txt").write_text("same content")     # dup of a
    (tmp_path / "c.txt").write_text("different content")  # unique
    (tmp_path / "d.log").write_text("same content")     # dup of a, other ext

    groups = find_duplicates(list(tmp_path.iterdir()))
    assert len(groups) == 1
    assert len(groups[0].paths) == 3  # a, b, d
    assert groups[0].wasted_bytes == len("same content") * 2


def test_no_duplicates(tmp_path: Path):
    (tmp_path / "a.txt").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    assert find_duplicates(list(tmp_path.iterdir())) == []


def test_identical_size_different_content_not_grouped(tmp_path: Path):
    (tmp_path / "a.txt").write_text("abc")
    (tmp_path / "b.txt").write_text("xyz")  # same size, different bytes
    assert find_duplicates(list(tmp_path.iterdir())) == []


def test_file_hash_matches_for_identical(tmp_path: Path):
    a = tmp_path / "a"; a.write_bytes(b"hello")
    b = tmp_path / "b"; b.write_bytes(b"hello")
    assert file_hash(a) == file_hash(b)


def test_dedupe_finds_files_inside_managed_dirs(tmp_path: Path):
    """After a sort, duplicates live inside category folders (managed dirs).
    A recursive dedupe with include_managed must still find them."""
    from cleanup.core.collect import collect_files
    from cleanup.core.config import Ruleset

    texts = tmp_path / "TEXTS"
    texts.mkdir()
    (texts / "a.txt").write_text("same")
    (texts / "b.txt").write_text("same")

    ruleset = Ruleset()
    # default recursive skips managed dirs -> misses them
    skipped = collect_files(tmp_path, ruleset, recursive=True)
    assert find_duplicates(skipped) == []
    # include_managed -> finds them
    seen = collect_files(tmp_path, ruleset, recursive=True, include_managed=True)
    assert len(find_duplicates(seen)) == 1


def test_apply_dedupe_move_keeps_first(tmp_path: Path):
    (tmp_path / "a.txt").write_text("dup")
    (tmp_path / "b.txt").write_text("dup")
    groups = find_duplicates(list(tmp_path.iterdir()))

    result = apply_dedupe(tmp_path, groups, action="move")
    assert len(result.moved) == 1
    # first copy stays, second moved into DUPLICATES/
    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()
    assert (tmp_path / "DUPLICATES" / "b.txt").exists()
