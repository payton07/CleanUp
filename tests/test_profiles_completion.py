"""Profiles (named config) and shell-completion generation."""

from __future__ import annotations

import json
from pathlib import Path

from cleanup.cli.completion import completion_script, option_strings
from cleanup.cli.main import build_parser
from cleanup.core.config import load_ruleset, profile_path


def test_profile_path_uses_cleanup_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLEANUP_HOME", str(tmp_path))
    assert profile_path("downloads") == tmp_path / "profiles" / "downloads.json"


def test_load_ruleset_applies_profile(tmp_path: Path):
    profile = tmp_path / "downloads.json"
    profile.write_text(json.dumps({"RULES": [{"ext": "torrent", "category": "TORRENTS"}]}))
    ruleset, message = load_ruleset(tmp_path / "somedir_that_may_not_exist", profile)
    assert len(ruleset.rules) == 1
    assert ruleset.rules[0].category == "TORRENTS"
    assert "profile" in message


def test_directory_config_overrides_profile(tmp_path: Path):
    profile = tmp_path / "p.json"
    profile.write_text(json.dumps({"THEMES": {"A": ["x"]}}))
    (tmp_path / "cleanup_config.json").write_text(json.dumps({"THEMES": {"B": ["y"]}}))
    ruleset, _ = load_ruleset(tmp_path, profile)
    # directory config applied last → its THEMES win
    assert "B" in ruleset.themes
    assert "A" not in ruleset.themes


def test_completion_lists_flags():
    parser = build_parser()
    opts = option_strings(parser)
    assert "--recursive" in opts and "--ai" in opts and "--profile" in opts
    bash = completion_script("bash", parser)
    assert "complete -F" in bash and "--watch" in bash
    zsh = completion_script("zsh", parser)
    assert "#compdef cleanup" in zsh
