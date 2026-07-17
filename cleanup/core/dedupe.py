"""Duplicate detection by content hash.

Files are compared by their actual bytes, not their names. A size pre-filter
avoids hashing files that can't possibly match (unique sizes are skipped
entirely), then remaining candidates are hashed with BLAKE2b.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .conflict import ConflictStrategy, resolve_conflict
from .manifest import MoveRecord
from .trash import send_to_trash

_CHUNK = 1 << 16  # 64 KiB
DUPLICATES_DIR = "DUPLICATES"


def file_hash(path: Path, chunk: int = _CHUNK) -> str:
    """Return the BLAKE2b hex digest of a file's contents."""
    digest = hashlib.blake2b()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class DuplicateGroup:
    digest: str
    size: int
    paths: list[Path]

    @property
    def wasted_bytes(self) -> int:
        """Space reclaimable by keeping a single copy."""
        return self.size * (len(self.paths) - 1)


def find_duplicates(files: list[Path]) -> list[DuplicateGroup]:
    """Group files with identical content. Only groups of 2+ are returned,
    each with its members in a stable (sorted) order."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in files:
        try:
            by_size[path.stat().st_size].append(path)
        except OSError:
            continue

    groups: list[DuplicateGroup] = []
    for size, candidates in by_size.items():
        if len(candidates) < 2:
            continue  # unique size → cannot be a duplicate
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for path in candidates:
            try:
                by_hash[file_hash(path)].append(path)
            except OSError:
                continue
        for digest, paths in by_hash.items():
            if len(paths) >= 2:
                groups.append(DuplicateGroup(digest=digest, size=size, paths=sorted(paths)))

    # Largest wasted space first — most impactful groups on top.
    groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return groups


@dataclass
class DedupeResult:
    moved: list[MoveRecord]
    trashed: int
    failed: list[Path]


def apply_dedupe(
    directory: Path,
    groups: list[DuplicateGroup],
    *,
    action: str,
    use_trash: bool = True,
) -> DedupeResult:
    """Resolve duplicate ``groups`` by keeping the first path in each group.

    - ``action="move"``  : relocate extra copies to ``DUPLICATES/`` (undoable;
      returns :class:`MoveRecord` entries for the history).
    - ``action="trash"`` : send extra copies to the OS trash.
    """
    moved: list[MoveRecord] = []
    trashed = 0
    failed: list[Path] = []
    dup_dir = directory / DUPLICATES_DIR

    for group in groups:
        for path in group.paths[1:]:  # keep the first copy
            if action == "trash":
                if use_trash and send_to_trash(path):
                    trashed += 1
                else:
                    failed.append(path)
            elif action == "move":
                target = resolve_conflict(dup_dir / path.name, ConflictStrategy.RENAME)
                if target is None:
                    continue
                dup_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                moved.append(MoveRecord.create(path, target, DUPLICATES_DIR, None))

    return DedupeResult(moved=moved, trashed=trashed, failed=failed)
