"""Config loading and schema validation."""

from __future__ import annotations

import json
from pathlib import Path

from cleanup.core.config import load_ruleset


def test_no_config_returns_defaults(tmp_path: Path):
    ruleset, message = load_ruleset(tmp_path)
    assert message is None
    assert "IMAGES" in ruleset.mime_categories
    assert ruleset.themes == {}


def test_valid_config_merges(tmp_path: Path):
    (tmp_path / "cleanup_config.json").write_text(json.dumps({
        "THEMES": {"Archi": ["UML", "Arch"]},
        "EXT_FALLBACK": {"CONFIGS": ["yaml", ".yml"]},
        "MIME_CATEGORIES": {"LOGS": "startswith:text/x-log"},
    }), encoding="utf-8")

    ruleset, message = load_ruleset(tmp_path)
    assert message.startswith("Configuration loaded")
    # keywords are lower-cased
    assert ruleset.themes["Archi"] == ["uml", "arch"]
    # extension dots stripped, lower-cased
    assert ruleset.ext_fallback["CONFIGS"] == {"yaml", "yml"}
    # custom category takes priority and its predicate works
    assert ruleset.mime_categories["LOGS"]("text/x-log-anything")
    # defaults are still present
    assert "IMAGES" in ruleset.mime_categories


def test_in_rule_predicate(tmp_path: Path):
    (tmp_path / "cleanup_config.json").write_text(json.dumps({
        "MIME_CATEGORIES": {"FONTS": "in:[font/ttf,font/otf]"},
    }), encoding="utf-8")
    ruleset, _ = load_ruleset(tmp_path)
    pred = ruleset.mime_categories["FONTS"]
    assert pred("font/ttf")
    assert not pred("font/woff")


def test_malformed_json_falls_back(tmp_path: Path):
    (tmp_path / "cleanup_config.json").write_text("{not valid json", encoding="utf-8")
    ruleset, message = load_ruleset(tmp_path)
    assert "Invalid" in message
    assert "IMAGES" in ruleset.mime_categories


def test_bad_rule_reports_error(tmp_path: Path):
    (tmp_path / "cleanup_config.json").write_text(json.dumps({
        "MIME_CATEGORIES": {"BAD": "matches:whatever"},
    }), encoding="utf-8")
    ruleset, message = load_ruleset(tmp_path)
    assert "Invalid" in message
    # defaults intact despite the bad rule
    assert "IMAGES" in ruleset.mime_categories


def test_managed_dirs_includes_themes(tmp_path: Path):
    (tmp_path / "cleanup_config.json").write_text(json.dumps({
        "THEMES": {"Work": ["invoice"]},
    }), encoding="utf-8")
    ruleset, _ = load_ruleset(tmp_path)
    assert "Work" in ruleset.managed_dirs
    assert "OTHERS" in ruleset.managed_dirs
    assert "IMAGES" in ruleset.managed_dirs
