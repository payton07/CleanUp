"""Web service layer.

Thin JSON-friendly bridge between the HTTP/WebSocket handlers and the core
engine. Every function takes a resolved directory and plain options, and returns
serialisable dicts. All the real work still lives in :mod:`cleanup.core`, so the
web GUI and the CLI share one code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..ai.classify import AiInteraction, CreativeClassifier, EmbeddingClassifier
from ..ai.ollama import OllamaClient
from ..core import detect
from ..core.collect import collect_files
from ..core.conflict import ConflictStrategy
from ..core.config import load_ruleset
from ..core.dedupe import apply_dedupe, find_duplicates
from ..core.engine import sort_files
from ..core.events import Event, FilePlanned, FileSkipped, Progress, ScanStarted, SortFinished
from ..core.history import HistoryStore
from ..core.organize import Scheme, make_organizer
from ..core.runlog import log_run


@dataclass
class SortOptions:
    recursive: bool = False
    smart: bool = False
    scheme: str = "type"
    conflict: str = "rename"
    extensions: list[str] = field(default_factory=list)
    clean_empty: bool = False
    no_trash: bool = False
    ai: bool = False
    ai_creative: bool = False
    ai_model: str | None = None

    @property
    def filter_exts(self) -> set[str] | None:
        return {e.lstrip(".").lower() for e in self.extensions} or None


def _ai_interaction(ruleset, opts: "SortOptions") -> AiInteraction | None:
    """Build an AiInteraction if AI is requested and the backend is available.

    Default uses embedding similarity; ``ai_creative`` uses a generative LLM.
    """
    if not (opts.ai or opts.ai_creative):
        return None
    client = OllamaClient(model=opts.ai_model)
    if not client.available():
        return None
    if opts.ai_creative:
        if not client.resolve_model():
            return None
        classifier = CreativeClassifier(client, list(ruleset.mime_categories.keys()))
    else:
        if not client.pick_embed_model():
            return None
        classifier = EmbeddingClassifier(client)
    return AiInteraction(classifier)


# ─── PATH SAFETY ────────────────────────────────────────────────────────────

def resolve_dir(path: str) -> Path:
    """Resolve and validate a user-supplied directory path."""
    directory = Path(path).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"'{directory}' is not a valid directory")
    return directory


# ─── BROWSE ─────────────────────────────────────────────────────────────────

def browse(path: str | None) -> dict:
    """List immediate subdirectories for the folder picker."""
    directory = Path(path).expanduser().resolve() if path else Path.home()
    if not directory.is_dir():
        directory = Path.home()
    try:
        dirs = sorted(
            (p.name for p in directory.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=str.lower,
        )
    except (PermissionError, OSError):
        dirs = []
    parent = str(directory.parent) if directory.parent != directory else None
    return {"path": str(directory), "parent": parent, "dirs": dirs}


# ─── SCAN (dry-run preview) ─────────────────────────────────────────────────

def scan(directory: Path, opts: SortOptions) -> dict:
    """Compute the planned moves without touching the filesystem."""
    ruleset, message = load_ruleset(directory)
    files = collect_files(
        directory, ruleset,
        recursive=opts.recursive,
        filter_exts=opts.filter_exts,
    )
    ai = _ai_interaction(ruleset, opts)

    items: list[dict] = []
    by_category: dict[str, int] = {}
    planned: list[FilePlanned] = []

    def capture(event: Event) -> None:
        if isinstance(event, FilePlanned):
            planned.append(event)

    sort_files(
        directory, files, ruleset,
        dry_run=True,
        smart=opts.smart,
        scheme=Scheme(opts.scheme),
        conflict_strategy=ConflictStrategy(opts.conflict),
        interaction=ai,
        on_event=capture,
    )

    ai_suggested = set(ai.suggested) if ai else set()
    for ev in planned:
        try:
            size = ev.src.stat().st_size
        except OSError:
            size = 0
        items.append({
            "name": ev.src.name,
            "src": _rel(ev.src, directory),
            "dest": _rel(ev.dest, directory),
            "category": ev.category,
            "theme": ev.theme,
            "size": size,
            "ai": str(ev.src) in ai_suggested,
        })
        by_category[ev.category] = by_category.get(ev.category, 0) + 1

    return {
        "directory": str(directory),
        "count": len(items),
        "content_detection": detect.CONTENT_DETECTION,
        "config_message": message,
        "ai_used": ai is not None,
        "by_category": by_category,
        "items": items,
    }


# ─── SORT (executed, event stream) ──────────────────────────────────────────

def run_sort(directory: Path, opts: SortOptions, on_event: Callable[[dict], None]) -> dict:
    """Execute the sort, forwarding serialised events to ``on_event``."""
    ruleset, _ = load_ruleset(directory)
    files = collect_files(
        directory, ruleset,
        recursive=opts.recursive,
        filter_exts=opts.filter_exts,
    )

    def forward(event: Event) -> None:
        on_event(_event_to_dict(event, directory))

    manifest = sort_files(
        directory, files, ruleset,
        smart=opts.smart,
        scheme=Scheme(opts.scheme),
        conflict_strategy=ConflictStrategy(opts.conflict),
        use_trash=not opts.no_trash,
        interaction=_ai_interaction(ruleset, opts),
        on_event=forward,
    )

    if manifest:
        HistoryStore(directory).record(f"sort by {opts.scheme}", manifest)
        log_run(directory, f"sort ({opts.scheme}, web): moved {len(manifest)} file(s)")

    removed = 0
    if opts.clean_empty:
        removed = _clean_empty(directory, ruleset.managed_dirs)

    return {"moved": len(manifest), "empty_removed": removed}


# ─── HISTORY ────────────────────────────────────────────────────────────────

def history(directory: Path) -> dict:
    store = HistoryStore(directory)
    return {
        "can_undo": store.can_undo,
        "can_redo": store.can_redo,
        "sessions": [
            {"id": s.id, "timestamp": s.timestamp, "label": s.label, "count": len(s.records)}
            for s in reversed(store.undo_stack())
        ],
    }


def undo(directory: Path) -> dict:
    ruleset, _ = load_ruleset(directory)
    result = HistoryStore(directory).undo(ruleset.managed_dirs)
    if not result.ok:
        return {"ok": False, "reason": result.reason}
    label = result.session.label if result.session else "?"
    log_run(directory, f"undo '{label}' (web): {result.restored} restored")
    return {"ok": True, "label": label, "restored": result.restored, "missing": len(result.missing)}


def redo(directory: Path) -> dict:
    result = HistoryStore(directory).redo()
    if not result.ok:
        return {"ok": False, "reason": result.reason}
    label = result.session.label if result.session else "?"
    log_run(directory, f"redo '{label}' (web): {result.restored} re-applied")
    return {"ok": True, "label": label, "restored": result.restored}


# ─── DEDUPE ─────────────────────────────────────────────────────────────────

def dedupe_scan(directory: Path, recursive: bool) -> dict:
    ruleset, _ = load_ruleset(directory)
    files = collect_files(directory, ruleset, recursive=recursive, include_managed=True)
    groups = find_duplicates(files)
    return {
        "groups": [
            {
                "digest": g.digest[:12],
                "size": g.size,
                "wasted": g.wasted_bytes,
                "paths": [_rel(p, directory) for p in g.paths],
            }
            for g in groups
        ],
        "total_wasted": sum(g.wasted_bytes for g in groups),
    }


def dedupe_apply(directory: Path, action: str, no_trash: bool) -> dict:
    ruleset, _ = load_ruleset(directory)
    files = collect_files(directory, ruleset, recursive=True, include_managed=True)
    groups = find_duplicates(files)
    result = apply_dedupe(directory, groups, action=action, use_trash=not no_trash)
    if result.moved:
        HistoryStore(directory).record("dedupe move", result.moved)
        log_run(directory, f"dedupe move (web): {len(result.moved)} file(s)")
    if result.trashed:
        log_run(directory, f"dedupe trash (web): {result.trashed} file(s)")
    return {"moved": len(result.moved), "trashed": result.trashed, "failed": len(result.failed)}


# ─── AI STATUS ──────────────────────────────────────────────────────────────

def ai_status() -> dict:
    """Report whether the local Ollama server is reachable and its models,
    including whether an embedding model (needed for the default mode) exists."""
    client = OllamaClient()
    if not client.available():
        return {"available": False, "models": [], "embed_model": None, "default": None}
    models = client.list_models()
    return {
        "available": True,
        "models": models,
        "default": client.resolve_model(),
        "embed_model": client.pick_embed_model(),
    }


# ─── HELPERS ────────────────────────────────────────────────────────────────

def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _event_to_dict(event: Event, directory: Path) -> dict:
    if isinstance(event, ScanStarted):
        return {"type": "scan_started", "total": event.total}
    if isinstance(event, FilePlanned):
        return {
            "type": "file_planned",
            "src": _rel(event.src, directory),
            "dest": _rel(event.dest, directory),
            "category": event.category,
            "theme": event.theme,
        }
    if isinstance(event, FileSkipped):
        return {"type": "file_skipped", "src": _rel(event.src, directory), "reason": event.reason}
    if isinstance(event, Progress):
        return {"type": "progress", "done": event.done, "total": event.total}
    if isinstance(event, SortFinished):
        return {"type": "finished", "moved": event.moved, "skipped": event.skipped}
    return {"type": "unknown"}


def _clean_empty(directory: Path, managed_dirs: set[str]) -> int:
    removed = 0
    for sub in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if sub.is_dir() and not any(sub.iterdir()):
            try:
                sub.rmdir()
                removed += 1
            except OSError:
                pass
    return removed
