"""User-defined sorting rules.

Rules let a user force a category by file name, extension, size, or age —
evaluated *before* content detection and AI. Defined in ``cleanup_config.json``:

    "RULES": [
      {"name": "*.facture.pdf", "category": "INVOICES"},
      {"ext": "psd", "category": "DESIGN"},
      {"min_size": "1GB", "category": "BIG"},
      {"older_than": "365d", "category": "ARCHIVE"}
    ]

First matching rule wins.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_DURATION_DAYS = {"d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}


def parse_size(value: object) -> int | None:
    """Parse '1GB', '500 MB', 2048 → bytes."""
    if isinstance(value, (int, float)):
        return int(value)
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMGT]?B)?\s*", str(value), re.IGNORECASE)
    if not m:
        return None
    return int(float(m.group(1)) * _SIZE_UNITS[(m.group(2) or "B").upper()])


def parse_duration_days(value: object) -> float | None:
    """Parse '365d', '2w', '6m', '1y', 30 → number of days."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*([\d.]+)\s*([dwmy]?)\s*", str(value), re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1)) * _DURATION_DAYS[(m.group(2) or "d").lower()]


@dataclass
class Rule:
    category: str
    name: str | None = None            # glob on the file name
    ext: str | None = None             # extension without the dot
    min_size: int | None = None
    max_size: int | None = None
    older_than_days: float | None = None
    newer_than_days: float | None = None

    def matches(self, path: Path, stat) -> bool:
        if self.name and not fnmatch.fnmatch(path.name.lower(), self.name.lower()):
            return False
        if self.ext and path.suffix.lstrip(".").lower() != self.ext.lstrip(".").lower():
            return False
        if self.min_size is not None and stat.st_size < self.min_size:
            return False
        if self.max_size is not None and stat.st_size > self.max_size:
            return False
        if self.older_than_days is not None or self.newer_than_days is not None:
            age_days = (datetime.now().timestamp() - stat.st_mtime) / 86400
            if self.older_than_days is not None and age_days < self.older_than_days:
                return False
            if self.newer_than_days is not None and age_days > self.newer_than_days:
                return False
        return True


def parse_rules(raw: list[dict]) -> list[Rule]:
    rules: list[Rule] = []
    for entry in raw:
        category = entry.get("category")
        if not category:
            continue
        rules.append(Rule(
            category=str(category).upper(),
            name=entry.get("name"),
            ext=entry.get("ext"),
            min_size=parse_size(entry["min_size"]) if "min_size" in entry else None,
            max_size=parse_size(entry["max_size"]) if "max_size" in entry else None,
            older_than_days=parse_duration_days(entry["older_than"]) if "older_than" in entry else None,
            newer_than_days=parse_duration_days(entry["newer_than"]) if "newer_than" in entry else None,
        ))
    return rules


def match_rule(path: Path, rules: list[Rule]) -> str | None:
    """Return the category of the first matching rule, or None."""
    if not rules:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    for rule in rules:
        if rule.matches(path, stat):
            return rule.category
    return None
