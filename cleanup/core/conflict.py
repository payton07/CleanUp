"""Name-collision resolution when a destination file already exists."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class ConflictStrategy(str, Enum):
    RENAME = "rename"
    SKIP = "skip"
    OVERWRITE = "overwrite"


def resolve_conflict(dest: Path, strategy: ConflictStrategy) -> Path | None:
    """Return the path to write to, or ``None`` if the file should be skipped.

    - no collision: return ``dest`` unchanged
    - ``SKIP``:      return ``None``
    - ``OVERWRITE``: return ``dest``
    - ``RENAME``:    return ``dest`` with a numbered ``_N`` suffix that is free
    """
    if not dest.exists():
        return dest
    if strategy == ConflictStrategy.SKIP:
        return None
    if strategy == ConflictStrategy.OVERWRITE:
        return dest

    stem, suffix = dest.stem, dest.suffix
    counter = 1
    while True:
        candidate = dest.parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
