"""Collection edge cases: symlink-cycle safety."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset


def test_recursive_skips_symlink_cycle(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x")
    sub = tmp_path / "sub"; sub.mkdir()
    (sub / "b.txt").write_text("y")
    # symlink loop pointing back at the root — must not cause infinite recursion
    (sub / "loop").symlink_to(tmp_path, target_is_directory=True)

    files = collect_files(tmp_path, Ruleset(), recursive=True)   # must terminate
    assert sorted(f.name for f in files) == ["a.txt", "b.txt"]
