"""Configuration and category rules.

Defines the default category ruleset and loads/validates an optional external
``cleanup_config.json`` via a pydantic schema. The old version parsed rule
strings by hand (``rule.split("startswith:")[1]``); that is replaced here by a
validated model so malformed configs fail with a clear message instead of a
confusing traceback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from .rules import Rule, parse_rules

CONFIG_FILE = "cleanup_config.json"


def profile_path(name: str) -> Path:
    """Path of a named profile config (``~/.config/cleanup/profiles/NAME.json``,
    or under ``$CLEANUP_HOME``)."""
    home = os.environ.get("CLEANUP_HOME")
    base = Path(home) if home else Path.home() / ".config" / "cleanup"
    return base / "profiles" / f"{name}.json"

# A predicate maps a MIME string to True/False for a category.
MimePredicate = Callable[[str], bool]

# ─── DEFAULT RULES ──────────────────────────────────────────────────────────

# Textual MIME types that should be treated as SCRIPTS rather than TEXTS.
_SCRIPT_TEXT_MIMES = frozenset({
    "text/x-python", "text/x-c", "text/x-c++", "text/x-java-source",
    "text/javascript", "application/javascript", "text/html", "text/css",
    "application/x-sh", "text/x-shellscript", "application/x-httpd-php",
    "text/x-ruby", "text/x-go", "text/x-rust",
})

DEFAULT_MIME_CATEGORIES: dict[str, MimePredicate] = {
    "IMAGES":   lambda m: m.startswith("image/"),
    "VIDEOS":   lambda m: m.startswith("video/"),
    "AUDIOS":   lambda m: m.startswith("audio/"),
    "SCRIPTS":  lambda m: m in _SCRIPT_TEXT_MIMES,
    "TEXTS":    lambda m: m.startswith("text/") and m not in _SCRIPT_TEXT_MIMES,
    "DOCS":     lambda m: m in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
    },
    "ARCHIVES": lambda m: m in {
        "application/zip", "application/x-tar", "application/gzip",
        "application/x-bzip2", "application/x-7z-compressed",
        "application/x-rar-compressed", "application/x-xz",
    },
}

DEFAULT_EXT_FALLBACK: dict[str, set[str]] = {
    "IMAGES":   {"jpeg", "jpg", "png", "gif", "bmp", "svg", "webp", "ico", "tiff", "heic"},
    "VIDEOS":   {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm"},
    "AUDIOS":   {"mp3", "wav", "flac", "aac", "ogg", "m4a"},
    "DOCS":     {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods"},
    "ARCHIVES": {"zip", "tar", "gz", "bz2", "7z", "rar", "xz"},
    "SCRIPTS":  {"py", "js", "ts", "c", "cpp", "h", "java", "html", "css", "sh", "rb", "go", "rs", "php"},
    "TEXTS":    {"txt", "md", "csv", "json", "xml", "yaml", "yml", "ini", "cfg", "log", "env"},
}

OTHERS = "OTHERS"


# ─── EXTERNAL CONFIG SCHEMA ─────────────────────────────────────────────────

class _ConfigModel(BaseModel):
    """Validated shape of ``cleanup_config.json``."""

    THEMES: dict[str, list[str]] = Field(default_factory=dict)
    EXT_FALLBACK: dict[str, list[str]] = Field(default_factory=dict)
    MIME_CATEGORIES: dict[str, str] = Field(default_factory=dict)
    RULES: list[dict] = Field(default_factory=list)

    @field_validator("MIME_CATEGORIES")
    @classmethod
    def _validate_rules(cls, value: dict[str, str]) -> dict[str, str]:
        for category, rule in value.items():
            if not (rule.startswith("startswith:") or rule.startswith("in:")):
                raise ValueError(
                    f"category {category!r}: rule must start with 'startswith:' "
                    f"or 'in:', got {rule!r}"
                )
        return value


def _rule_to_predicate(rule: str) -> MimePredicate:
    """Turn a validated rule string into a MIME predicate."""
    if rule.startswith("startswith:"):
        prefix = rule[len("startswith:"):]
        return lambda m, p=prefix: m.startswith(p)
    # rule.startswith("in:")
    allowed = {
        item.strip()
        for item in rule[len("in:"):].strip("[] ").split(",")
        if item.strip()
    }
    return lambda m, a=allowed: m in a


# ─── RESOLVED RULESET ───────────────────────────────────────────────────────

@dataclass
class Ruleset:
    """The effective set of rules used by detection, after merging defaults
    with any external configuration."""

    mime_categories: dict[str, MimePredicate] = field(
        default_factory=lambda: dict(DEFAULT_MIME_CATEGORIES)
    )
    ext_fallback: dict[str, set[str]] = field(
        default_factory=lambda: {k: set(v) for k, v in DEFAULT_EXT_FALLBACK.items()}
    )
    themes: dict[str, list[str]] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)

    @property
    def managed_dirs(self) -> set[str]:
        """Category and theme folder names the sorter creates and must not
        re-scan on a recursive run."""
        return (set(self.mime_categories) | {OTHERS, "DUPLICATES"}
                | set(self.themes) | {r.category for r in self.rules})


def _apply_model(ruleset: Ruleset, model: _ConfigModel) -> None:
    """Merge a validated config model into ``ruleset`` in place."""
    # Custom MIME categories are inserted first so they take priority over the
    # defaults, matching the old "override then keep the rest" behaviour.
    if model.MIME_CATEGORIES:
        merged: dict[str, MimePredicate] = {
            cat: _rule_to_predicate(rule)
            for cat, rule in model.MIME_CATEGORIES.items()
        }
        for cat, pred in ruleset.mime_categories.items():
            merged.setdefault(cat, pred)
        ruleset.mime_categories = merged

    for cat, exts in model.EXT_FALLBACK.items():
        ruleset.ext_fallback[cat] = {e.lstrip(".").lower() for e in exts}

    if model.THEMES:
        ruleset.themes = {
            theme: [k.lower() for k in keywords]
            for theme, keywords in model.THEMES.items()
        }

    if model.RULES:
        ruleset.rules = parse_rules(model.RULES)


def _load_model(path: Path) -> tuple[_ConfigModel | None, str | None]:
    """Load and validate a config file. Returns (model, error-message)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _ConfigModel.model_validate(raw), None
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        return None, f"Invalid {path.name}, using defaults: {exc}"


def load_ruleset(directory: Path, profile_path: Path | None = None) -> tuple[Ruleset, str | None]:
    """Build a :class:`Ruleset` from defaults, an optional profile, and the
    directory's ``cleanup_config.json``.

    Sources apply in order (later overrides earlier): defaults → profile →
    directory config. Returns ``(ruleset, message)``; never raises on a bad
    file — reports the problem and continues with what loaded.
    """
    ruleset = Ruleset()
    messages: list[str] = []

    for path in (profile_path, directory / CONFIG_FILE):
        if path is None or not path.exists():
            continue
        model, error = _load_model(path)
        if error:
            messages.append(error)
        elif model is not None:
            _apply_model(ruleset, model)
            label = "profile" if path is profile_path else CONFIG_FILE
            messages.append(f"Configuration loaded from {label} ({path.name})")

    return ruleset, ("; ".join(messages) if messages else None)
