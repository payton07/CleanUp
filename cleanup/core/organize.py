"""Destination-layout schemes.

The engine asks an *organizer* where a file should go, given its category and
(optional) theme. This decouples "what kind of file is this" (detection) from
"where should it live" (layout), so new schemes are a one-line addition.

Schemes:
- ``TYPE`` — ``<theme>/<category>``               (the classic layout)
- ``DATE`` — ``<theme>/<category>/<YYYY>/<MM>``    (by last-modified date)
- ``SIZE`` — ``<theme>/<category>/<bucket>``       (by size bucket)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

# The relative destination directory for a file, under the target root.
Organizer = Callable[[Path, str, str | None], Path]


class Scheme(str, Enum):
    TYPE = "type"
    DATE = "date"
    SIZE = "size"


_KB = 1024
_MB = _KB * 1024
_GB = _MB * 1024

# (upper-bound-exclusive, label); anything larger falls through to "huge".
_SIZE_BUCKETS: tuple[tuple[int, str], ...] = (
    (_MB, "tiny_lt_1MB"),
    (10 * _MB, "small_lt_10MB"),
    (100 * _MB, "medium_lt_100MB"),
    (_GB, "large_lt_1GB"),
)


def size_bucket(size: int) -> str:
    for upper, label in _SIZE_BUCKETS:
        if size < upper:
            return label
    return "huge_gte_1GB"


def _base(category: str, theme: str | None) -> Path:
    return Path(theme) / category if theme else Path(category)


def make_organizer(scheme: Scheme = Scheme.TYPE) -> Organizer:
    """Return an organizer function for ``scheme``."""
    if scheme == Scheme.TYPE:
        def by_type(file: Path, category: str, theme: str | None) -> Path:
            return _base(category, theme)
        return by_type

    if scheme == Scheme.DATE:
        def by_date(file: Path, category: str, theme: str | None) -> Path:
            try:
                dt = datetime.fromtimestamp(file.stat().st_mtime)
            except OSError:
                dt = datetime.now()
            return _base(category, theme) / f"{dt:%Y}" / f"{dt:%m}"
        return by_date

    # Scheme.SIZE
    def by_size(file: Path, category: str, theme: str | None) -> Path:
        try:
            size = file.stat().st_size
        except OSError:
            size = 0
        return _base(category, theme) / size_bucket(size)
    return by_size
