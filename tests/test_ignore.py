"""`.cleanupignore` parsing and collection exclusion."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset
from cleanup.core.ignore import is_ignored, load_ignore_patterns


def test_load_patterns_skips_comments_and_blanks(tmp_path: Path):
    (tmp_path / ".cleanupignore").write_text("# comment\n*.tmp\n\nsecret*\n")
    assert load_ignore_patterns(tmp_path) == ["*.tmp", "secret*"]


def test_is_ignored_name_and_path():
    pats = ["*.tmp", "build/"]
    assert is_ignored("a.tmp", "a.tmp", pats)
    assert is_ignored("build/out.js", "out.js", pats)
    assert not is_ignored("src/app.py", "app.py", pats)


def test_collect_excludes_ignored_files(tmp_path: Path):
    (tmp_path / ".cleanupignore").write_text("*.tmp\nsecret.txt\n")
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / "scratch.tmp").write_text("x")
    (tmp_path / "secret.txt").write_text("x")

    names = {p.name for p in collect_files(tmp_path, Ruleset())}
    assert names == {"keep.txt"}


def test_collect_excludes_ignored_dir(tmp_path: Path):
    (tmp_path / ".cleanupignore").write_text("node_modules/\n")
    (tmp_path / "app.py").write_text("x")
    nm = tmp_path / "node_modules"; nm.mkdir()
    (nm / "lib.js").write_text("x")

    names = {p.name for p in collect_files(tmp_path, Ruleset(), recursive=True)}
    assert names == {"app.py"}


def test_ignore_file_itself_never_collected(tmp_path: Path):
    (tmp_path / ".cleanupignore").write_text("*.tmp\n")
    (tmp_path / "a.txt").write_text("x")
    names = {p.name for p in collect_files(tmp_path, Ruleset())}
    assert ".cleanupignore" not in names
