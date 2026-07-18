"""Directory-stats tests."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.config import Ruleset
from cleanup.core.stats import compute_stats

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 40 + b"\xff\xd9"


def test_compute_stats_basic(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello world")   # 11 bytes, TEXTS
    (tmp_path / "b.txt").write_text("hello world")   # duplicate of a
    (tmp_path / "app.py").write_text("print(1)")     # SCRIPTS
    (tmp_path / "photo.jpg").write_bytes(_JPEG)      # IMAGES

    stats = compute_stats(tmp_path, Ruleset())

    assert stats.total_files == 4
    assert stats.total_size == 11 + 11 + len("print(1)") + len(_JPEG)

    cats = {c.category: c for c in stats.categories}
    assert cats["TEXTS"].count == 2
    assert cats["SCRIPTS"].count == 1
    assert cats["IMAGES"].count == 1

    # duplicates: a.txt / b.txt identical → one copy reclaimable
    assert stats.duplicate_groups == 1
    assert stats.reclaimable == 11

    # largest sorted descending, month histogram present
    sizes = [s for _, s in stats.largest]
    assert sizes == sorted(sizes, reverse=True)
    assert len(stats.by_month) >= 1


def test_categories_sorted_by_size(tmp_path: Path):
    (tmp_path / "small.txt").write_text("x")
    (tmp_path / "big.py").write_text("y" * 5000)
    stats = compute_stats(tmp_path, Ruleset())
    assert stats.categories[0].category == "SCRIPTS"  # biggest first


def test_include_duplicates_false_skips_hashing(tmp_path: Path):
    (tmp_path / "a.txt").write_text("dup")
    (tmp_path / "b.txt").write_text("dup")
    stats = compute_stats(tmp_path, Ruleset(), include_duplicates=False)
    assert stats.duplicate_groups == 0
    assert stats.reclaimable == 0


def test_empty_directory(tmp_path: Path):
    stats = compute_stats(tmp_path, Ruleset())
    assert stats.total_files == 0
    assert stats.categories == []


def test_stats_includes_sorted_subdirs(tmp_path: Path):
    """Stats analyse already-sorted category folders too."""
    (tmp_path / "TEXTS").mkdir()
    (tmp_path / "TEXTS" / "note.txt").write_text("hi")
    stats = compute_stats(tmp_path, Ruleset())
    assert stats.total_files == 1
