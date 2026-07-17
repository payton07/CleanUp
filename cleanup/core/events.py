"""Events emitted by the engine during a sort run.

The engine is UI-agnostic: it pushes these dataclasses to an ``on_event``
callback. The CLI renders them with Rich; the future web UI will forward the
same events over a WebSocket. One source of truth, many faces.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScanStarted:
    total: int


@dataclass
class FilePlanned:
    """A move that has been decided (and, unless dry-run, is about to happen)."""
    src: Path
    dest: Path
    category: str
    theme: str | None
    dry_run: bool


@dataclass
class FileSkipped:
    src: Path
    reason: str


@dataclass
class Progress:
    done: int
    total: int


@dataclass
class SortFinished:
    moved: int
    skipped: int
    dry_run: bool


Event = ScanStarted | FilePlanned | FileSkipped | Progress | SortFinished
