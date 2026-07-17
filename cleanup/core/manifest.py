"""The move record — the atomic unit persisted for undo/redo.

Session grouping, undo, and redo live in :mod:`cleanup.core.history`. This
module only defines the record and the legacy manifest filename (still reserved
so old ``.cleanup_manifest.json`` files are never treated as sortable input).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Retained as a reserved name for backward compatibility with pre-0.2 runs.
MANIFEST_FILE = ".cleanup_manifest.json"


@dataclass
class MoveRecord:
    src: str
    dest: str
    category: str
    theme: str | None
    timestamp: str

    @classmethod
    def create(cls, src: Path, dest: Path, category: str, theme: str | None) -> "MoveRecord":
        return cls(
            src=str(src),
            dest=str(dest),
            category=category,
            theme=theme,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )
