"""Name-collision resolution when a destination file already exists."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class ConflictStrategy(str, Enum):
    RENAME = "rename"
    SKIP = "skip"
    OVERWRITE = "overwrite"


def resolve_conflict(
    dest: Path,
    strategy: ConflictStrategy,
    taken: set[Path] | None = None,
) -> Path | None:
    """Return the path to write to, or ``None`` if the file should be skipped.

    - no collision: return ``dest`` unchanged
    - ``SKIP``:      return ``None``
    - ``OVERWRITE``: return ``dest``
    - ``RENAME``:    return ``dest`` with a numbered ``_N`` suffix that is free

    ``taken`` lets a caller reserve paths that aren't on disk yet (e.g. dry-run
    previews of earlier files in the same batch), so collisions are simulated
    accurately.
    """
    taken = taken or set()

    def occupied(p: Path) -> bool:
        return p in taken or p.exists()

    if not occupied(dest):
        return dest
    if strategy == ConflictStrategy.SKIP:
        return None
    if strategy == ConflictStrategy.OVERWRITE:
        return dest

    stem, suffix = dest.stem, dest.suffix
    counter = 1
    while True:
        candidate = dest.parent / f"{stem}_{counter}{suffix}"
        if not occupied(candidate):
            return candidate
        counter += 1
