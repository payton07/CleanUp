"""Persistent memory of user corrections.

When a user overrides a suggested category, we store ``(file embedding, chosen
category)``. Later, a new file whose embedding is very close to a remembered one
is filed the same way — the tool learns your preferences.

Stored as JSON at ``~/.config/cleanup/decisions.json`` (override the directory
with ``CLEANUP_HOME``). The store is global (not per-folder), so a correction
made in the web GUI also benefits the CLI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .classify import _cosine


def default_store_path() -> Path:
    home = os.environ.get("CLEANUP_HOME")
    base = Path(home) if home else Path.home() / ".config" / "cleanup"
    return base / "decisions.json"


@dataclass
class Decision:
    embedding: list[float]
    category: str
    timestamp: str


class DecisionStore:
    """A small nearest-neighbour store of past corrections."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_store_path()
        self._decisions: list[Decision] = self._load()

    def _load(self) -> list[Decision]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [Decision(**d) for d in raw]
        except (json.JSONDecodeError, TypeError, OSError):
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"embedding": d.embedding, "category": d.category, "timestamp": d.timestamp}
            for d in self._decisions
        ]
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._decisions)

    def add(self, embedding: list[float], category: str) -> None:
        """Remember that a file with this embedding belongs in ``category``."""
        self._decisions.append(Decision(
            embedding=list(embedding),
            category=category,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        ))
        self._save()

    def nearest(self, embedding: list[float]) -> tuple[str, float] | None:
        """Return ``(category, score)`` of the closest past decision, or None."""
        if not self._decisions:
            return None
        best = max(
            ((d.category, _cosine(embedding, d.embedding)) for d in self._decisions),
            key=lambda pair: pair[1],
        )
        return best
