"""Watch mode — keep a directory tidy as new files arrive.

A lightweight polling watcher (no external dependency): each *tick* lists the
currently-sortable files and moves the ones whose size has stayed stable since
the previous tick. The size-stability check debounces in-progress writes (a
download is only sorted once it has finished growing).

The class is UI-agnostic: it reuses the sort engine, records every batch in the
undo history, and reports through callbacks. ``tick()`` is a pure step so it can
be unit-tested without threads or timing.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .collect import collect_files
from .conflict import ConflictStrategy
from .config import Ruleset
from .engine import Interaction, sort_files
from .events import Event
from .history import HistoryStore
from .manifest import MoveRecord
from .organize import Scheme


class Watcher:
    def __init__(
        self,
        directory: Path,
        ruleset: Ruleset,
        *,
        recursive: bool = False,
        filter_exts: set[str] | None = None,
        conflict: ConflictStrategy = ConflictStrategy.RENAME,
        smart: bool = False,
        scheme: Scheme = Scheme.TYPE,
        use_trash: bool = True,
        interaction: Interaction | None = None,
        poll_interval: float = 2.0,
        on_event: Callable[[Event], None] | None = None,
        on_sorted: Callable[[list[MoveRecord]], None] | None = None,
    ):
        self.directory = directory
        self.ruleset = ruleset
        self.recursive = recursive
        self.filter_exts = filter_exts
        self.conflict = conflict
        self.smart = smart
        self.scheme = scheme
        self.use_trash = use_trash
        self.interaction = interaction
        self.poll_interval = poll_interval
        self.on_event = on_event
        self.on_sorted = on_sorted

        self._sizes: dict[Path, int] = {}
        self._running = False

    def _stable_files(self) -> list[Path]:
        """Files present now with the same size as the previous tick.

        A file must be seen on two consecutive ticks with an unchanged size to
        count as stable — this debounces files that are still being written.
        """
        current: dict[Path, int] = {}
        stable: list[Path] = []
        for f in collect_files(
            self.directory, self.ruleset,
            recursive=self.recursive, filter_exts=self.filter_exts,
        ):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            current[f] = size
            if self._sizes.get(f) == size:
                stable.append(f)
        self._sizes = current
        return stable

    def tick(self) -> list[MoveRecord]:
        """One watch step: sort every file that has stabilised. Returns the
        moves performed (empty if nothing was ready)."""
        stable = self._stable_files()
        if not stable:
            return []
        manifest = sort_files(
            self.directory, stable, self.ruleset,
            conflict_strategy=self.conflict,
            smart=self.smart,
            scheme=self.scheme,
            use_trash=self.use_trash,
            interaction=self.interaction,
            on_event=self.on_event,
        )
        if manifest:
            HistoryStore(self.directory).record("watch auto-sort", manifest)
            if self.on_sorted:
                self.on_sorted(manifest)
        return manifest

    def run(self) -> None:
        """Poll until :meth:`stop` is called (or KeyboardInterrupt)."""
        self._running = True
        while self._running:
            self.tick()
            # Sleep in small slices so stop() is responsive.
            slept = 0.0
            while self._running and slept < self.poll_interval:
                time.sleep(min(0.2, self.poll_interval - slept))
                slept += 0.2

    def stop(self) -> None:
        self._running = False
