"""Multi-level undo/redo history.

Replaces the single-level manifest with a stack of *sessions*. Each executed
sort (or dedupe-move) appends a session to the undo stack. ``undo`` reverses the
most recent session and pushes it onto the redo stack; ``redo`` re-applies it.
Starting a fresh sort clears the redo stack (standard undo semantics).

Persisted to ``.cleanup_history.json`` in the target directory.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .manifest import MoveRecord

HISTORY_FILE = ".cleanup_history.json"


@dataclass
class Session:
    id: str
    timestamp: str
    label: str
    records: list[MoveRecord]

    @classmethod
    def create(cls, label: str, records: list[MoveRecord]) -> "Session":
        return cls(
            id=uuid.uuid4().hex[:8],
            timestamp=datetime.now().isoformat(timespec="seconds"),
            label=label,
            records=records,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "label": self.label,
            "records": [asdict(r) for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            label=data["label"],
            records=[MoveRecord(**r) for r in data["records"]],
        )


@dataclass
class _State:
    undo: list[Session] = field(default_factory=list)
    redo: list[Session] = field(default_factory=list)


@dataclass
class UndoResult:
    ok: bool
    session: Session | None = None
    restored: int = 0
    missing: list[str] = field(default_factory=list)
    reason: str = ""


class HistoryStore:
    """Load/save the undo & redo stacks for one directory."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / HISTORY_FILE
        self._state = self._load()

    # ── persistence ──
    def _load(self) -> _State:
        if not self.path.exists():
            return _State()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return _State(
                undo=[Session.from_dict(s) for s in raw.get("undo", [])],
                redo=[Session.from_dict(s) for s in raw.get("redo", [])],
            )
        except (json.JSONDecodeError, KeyError, OSError):
            return _State()

    def _save(self) -> None:
        if not self._state.undo and not self._state.redo:
            self.path.unlink(missing_ok=True)
            return
        payload = {
            "undo": [s.to_dict() for s in self._state.undo],
            "redo": [s.to_dict() for s in self._state.redo],
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── introspection ──
    @property
    def can_undo(self) -> bool:
        return bool(self._state.undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._state.redo)

    def undo_stack(self) -> list[Session]:
        return list(self._state.undo)

    # ── mutations ──
    def record(self, label: str, records: list[MoveRecord]) -> Session | None:
        """Push a new session; clears the redo stack. No-op for empty records."""
        if not records:
            return None
        session = Session.create(label, records)
        self._state.undo.append(session)
        self._state.redo.clear()
        self._save()
        return session

    def undo(self, managed_dirs: set[str], *, on_progress=None) -> UndoResult:
        """Reverse the most recent session (move dest → src)."""
        if not self._state.undo:
            return UndoResult(ok=False, reason="nothing-to-undo")
        session = self._state.undo.pop()
        restored, missing = _apply(session.records, forward=False, on_progress=on_progress)
        _prune_empty_dirs(self.directory, managed_dirs)
        self._state.redo.append(session)
        self._save()
        return UndoResult(ok=True, session=session, restored=restored, missing=missing)

    def redo(self, *, on_progress=None) -> UndoResult:
        """Re-apply the most recently undone session (move src → dest)."""
        if not self._state.redo:
            return UndoResult(ok=False, reason="nothing-to-redo")
        session = self._state.redo.pop()
        restored, missing = _apply(session.records, forward=True, on_progress=on_progress)
        self._state.undo.append(session)
        self._save()
        return UndoResult(ok=True, session=session, restored=restored, missing=missing)


def _apply(records: list[MoveRecord], *, forward: bool, on_progress=None) -> tuple[int, list[str]]:
    """Move files forward (src→dest) or backward (dest→src). Backward walks the
    records in reverse so later moves are undone first."""
    ordered = records if forward else list(reversed(records))
    moved = 0
    missing: list[str] = []
    for index, record in enumerate(ordered, start=1):
        src, dest = Path(record.src), Path(record.dest)
        source, target = (src, dest) if forward else (dest, src)
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved += 1
        else:
            missing.append(str(source))
        if on_progress:
            on_progress(index, len(ordered))
    return moved, missing


def _prune_empty_dirs(directory: Path, managed_dirs: set[str]) -> None:
    """Remove empty category/theme folders (including nested date/size dirs)."""
    for folder in managed_dirs:
        root = directory / folder
        if not root.is_dir():
            continue
        # Deepest first so parents can be removed once children are gone.
        for sub in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()
        if not any(root.iterdir()):
            root.rmdir()
