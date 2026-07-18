"""Conflict-resolution strategy tests."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.conflict import ConflictStrategy, resolve_conflict


def test_no_collision_returns_dest(tmp_path: Path):
    dest = tmp_path / "file.txt"
    assert resolve_conflict(dest, ConflictStrategy.RENAME) == dest


def test_skip_returns_none(tmp_path: Path):
    dest = tmp_path / "file.txt"
    dest.write_text("x")
    assert resolve_conflict(dest, ConflictStrategy.SKIP) is None


def test_overwrite_returns_dest(tmp_path: Path):
    dest = tmp_path / "file.txt"
    dest.write_text("x")
    assert resolve_conflict(dest, ConflictStrategy.OVERWRITE) == dest


def test_rename_increments(tmp_path: Path):
    dest = tmp_path / "file.txt"
    dest.write_text("x")
    (tmp_path / "file_1.txt").write_text("x")
    assert resolve_conflict(dest, ConflictStrategy.RENAME) == tmp_path / "file_2.txt"


def test_rename_around_taken_paths(tmp_path: Path):
    dest = tmp_path / "f.txt"          # not on disk
    taken = {dest}
    assert resolve_conflict(dest, ConflictStrategy.RENAME, taken) == tmp_path / "f_1.txt"


def test_taken_skip_returns_none(tmp_path: Path):
    dest = tmp_path / "f.txt"
    assert resolve_conflict(dest, ConflictStrategy.SKIP, {dest}) is None


def test_taken_free_path_returned(tmp_path: Path):
    dest = tmp_path / "f.txt"
    assert resolve_conflict(dest, ConflictStrategy.RENAME, set()) == dest
