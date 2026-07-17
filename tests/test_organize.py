"""Layout-scheme tests: type, date, size."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset
from cleanup.core.engine import sort_files
from cleanup.core.organize import Scheme, make_organizer, size_bucket


def test_size_bucket_boundaries():
    assert size_bucket(0) == "tiny_lt_1MB"
    assert size_bucket(5 * 1024 * 1024) == "small_lt_10MB"
    assert size_bucket(2 * 1024 * 1024 * 1024) == "huge_gte_1GB"


def test_type_scheme_default(tmp_path: Path):
    org = make_organizer(Scheme.TYPE)
    assert org(tmp_path / "x.py", "SCRIPTS", None) == Path("SCRIPTS")
    assert org(tmp_path / "x.py", "SCRIPTS", "Work") == Path("Work/SCRIPTS")


def test_date_scheme_uses_mtime(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("hi")
    # pin mtime to a known date
    when = datetime(2021, 3, 15).timestamp()
    os.utime(f, (when, when))
    org = make_organizer(Scheme.DATE)
    assert org(f, "TEXTS", None) == Path("TEXTS/2021/03")


def test_sort_by_date_creates_nested_dirs(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("hi")
    when = datetime(2019, 12, 1).timestamp()
    os.utime(f, (when, when))
    ruleset = Ruleset()
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset, scheme=Scheme.DATE)
    assert (tmp_path / "TEXTS" / "2019" / "12" / "note.txt").exists()


def test_sort_by_size(tmp_path: Path):
    small = tmp_path / "small.txt"
    small.write_text("tiny")
    ruleset = Ruleset()
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset, scheme=Scheme.SIZE)
    assert (tmp_path / "TEXTS" / "tiny_lt_1MB" / "small.txt").exists()
