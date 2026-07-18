"""Sort orchestration.

``sort_files`` ties detection, conflict resolution and moving together. It stays
free of any terminal/UI code: progress is reported through ``on_event`` and any
interactive decisions are delegated to an :class:`Interaction` object. The
default :class:`Interaction` is fully non-interactive, so batch/dry-run and the
web backend can reuse the exact same code path the CLI uses.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .conflict import ConflictStrategy, resolve_conflict
from .config import OTHERS, Ruleset
from .detect import detect_category, detect_theme
from .events import (
    Event,
    FilePlanned,
    FileSkipped,
    Progress,
    ScanStarted,
    SortFinished,
)
from .manifest import MoveRecord
from .organize import Organizer, Scheme, make_organizer
from .rules import match_rule
from .trash import send_to_trash


@dataclass
class UnknownDecision:
    """What to do with a file the rules classified as OTHERS."""
    action: str  # "others" | "skip" | "category"
    category: str | None = None


class Interaction:
    """Hooks the engine calls when a human decision may be needed.

    The defaults are non-interactive: keep everything, never skip, honour the
    configured conflict strategy. Subclasses (the CLI's Rich prompts, the web
    UI's WebSocket round-trips) override selectively.
    """

    def confirm_theme(self, file: Path, theme: str) -> bool:
        return True

    def handle_unknown(self, file: Path) -> UnknownDecision:
        return UnknownDecision(action="others")

    def refine_category(self, file: Path, category: str) -> str:
        """Optionally replace a detected category with a better one (e.g. an
        AI tagger promoting a generic TEXTS file to INVOICES). Default: no-op."""
        return category

    def resolve_conflict(self, target: Path, default: ConflictStrategy) -> ConflictStrategy:
        return default


OnEvent = Callable[[Event], None]


def sort_files(
    directory: Path,
    files: list[Path],
    ruleset: Ruleset,
    *,
    conflict_strategy: ConflictStrategy = ConflictStrategy.RENAME,
    dry_run: bool = False,
    smart: bool = False,
    scheme: Scheme = Scheme.TYPE,
    organizer: Organizer | None = None,
    use_trash: bool = True,
    interaction: Interaction | None = None,
    on_event: OnEvent | None = None,
) -> list[MoveRecord]:
    """Move each file to a destination under ``directory`` decided by the
    organizer (default: ``<theme>/<category>``).

    Returns the manifest of executed moves (empty on dry-run). Emits
    :mod:`~cleanup.core.events` through ``on_event``.
    """
    interaction = interaction or Interaction()
    organizer = organizer or make_organizer(scheme)
    emit: OnEvent = on_event or (lambda _event: None)

    manifest: list[MoveRecord] = []
    skipped = 0
    total = len(files)
    theme_decisions: dict[str, bool] = {}
    dynamic_managed = set(ruleset.managed_dirs)

    emit(ScanStarted(total=total))

    for index, file in enumerate(files, start=1):
        # A user rule, if it matches, is authoritative (skips detection + AI).
        rule_category = match_rule(file, ruleset.rules)
        category = rule_category if rule_category is not None else detect_category(file, ruleset)
        theme = detect_theme(file, ruleset) if smart else None

        # Theme confirmation (cached per theme).
        if theme is not None:
            if theme not in theme_decisions:
                theme_decisions[theme] = interaction.confirm_theme(file, theme)
            if not theme_decisions[theme]:
                theme = None

        # Unknown handling (rules never yield OTHERS unless explicitly set).
        if rule_category is None and category == OTHERS:
            decision = interaction.handle_unknown(file)
            if decision.action == "skip":
                skipped += 1
                emit(FileSkipped(src=file, reason="unknown"))
                emit(Progress(done=index, total=total))
                continue
            if decision.action == "category" and decision.category:
                category = decision.category
                dynamic_managed.add(category)

        # Optional AI refinement of ambiguous categories — skipped when a rule
        # already decided the category.
        if rule_category is None:
            category = interaction.refine_category(file, category)
        dynamic_managed.add(category)

        dest_dir = directory / organizer(file, category, theme)
        target = dest_dir / file.name

        strategy = conflict_strategy
        if target.exists():
            strategy = interaction.resolve_conflict(target, conflict_strategy)

        resolved = resolve_conflict(target, strategy)
        if resolved is None:
            skipped += 1
            emit(FileSkipped(src=file, reason="conflict"))
            emit(Progress(done=index, total=total))
            continue

        emit(FilePlanned(
            src=file, dest=resolved, category=category, theme=theme, dry_run=dry_run,
        ))

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Overwrite: preserve the file being replaced by trashing it first
            # (recoverable) rather than letting move() destroy it outright.
            if strategy == ConflictStrategy.OVERWRITE and resolved.exists() and use_trash:
                send_to_trash(resolved)
            shutil.move(str(file), str(resolved))
            manifest.append(MoveRecord.create(file, resolved, category, theme))

        emit(Progress(done=index, total=total))

    emit(SortFinished(moved=len(manifest), skipped=skipped, dry_run=dry_run))
    return manifest
