"""User-rule parsing, matching, and engine integration."""

from __future__ import annotations

import os
import time
from pathlib import Path

from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset
from cleanup.core.engine import sort_files
from cleanup.core.rules import Rule, match_rule, parse_rules, parse_size, parse_duration_days


def test_parse_size():
    assert parse_size("1GB") == 1024**3
    assert parse_size("500 MB") == 500 * 1024**2
    assert parse_size(2048) == 2048
    assert parse_size("nonsense") is None


def test_parse_duration_days():
    assert parse_duration_days("365d") == 365
    assert parse_duration_days("2w") == 14
    assert parse_duration_days("6m") == 180
    assert parse_duration_days("1y") == 365


def test_rule_matches_name_and_ext(tmp_path: Path):
    f = tmp_path / "acme.facture.pdf"; f.write_text("x")
    st = f.stat()
    assert Rule("INVOICES", name="*.facture.pdf").matches(f, st)
    assert not Rule("INVOICES", name="*.devis.pdf").matches(f, st)
    assert Rule("DOCS", ext="pdf").matches(f, st)
    assert not Rule("DOCS", ext="png").matches(f, st)


def test_rule_matches_size(tmp_path: Path):
    f = tmp_path / "big.bin"; f.write_bytes(b"x" * 5000)
    st = f.stat()
    assert Rule("BIG", min_size=1000).matches(f, st)
    assert not Rule("BIG", min_size=10000).matches(f, st)
    assert Rule("SMALL", max_size=10000).matches(f, st)


def test_rule_matches_age(tmp_path: Path):
    f = tmp_path / "old.txt"; f.write_text("x")
    old = time.time() - 400 * 86400
    os.utime(f, (old, old))
    st = f.stat()
    assert Rule("ARCHIVE", older_than_days=365).matches(f, st)
    assert not Rule("RECENT", newer_than_days=30).matches(f, st)


def test_match_rule_first_wins(tmp_path: Path):
    f = tmp_path / "a.log"; f.write_text("x")
    rules = [Rule("LOGS", ext="log"), Rule("TEXT", ext="log")]
    assert match_rule(f, rules) == "LOGS"


def test_parse_rules_from_config():
    rules = parse_rules([
        {"name": "*.facture.pdf", "category": "invoices"},
        {"min_size": "1GB", "category": "BIG"},
        {"category": None},          # skipped
        {"no_category": 1},          # skipped
    ])
    assert len(rules) == 2
    assert rules[0].category == "INVOICES"   # upper-cased
    assert rules[1].min_size == 1024**3


def test_engine_applies_rule_over_detection(tmp_path: Path):
    # a .txt would normally be TEXTS; a rule forces INVOICES by name
    (tmp_path / "acme.facture.txt").write_text("Total due $100")
    ruleset = Ruleset(rules=[Rule("INVOICES", name="*.facture.txt")])
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset)
    assert (tmp_path / "INVOICES" / "acme.facture.txt").exists()
    assert not (tmp_path / "TEXTS").exists()
