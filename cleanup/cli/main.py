#!/usr/bin/env python3
"""CleanUp command-line interface.

Thin presentation layer: parses arguments, wires a Rich renderer to the engine's
event stream, and provides interactive prompts. All real work lives in
:mod:`cleanup.core`.
"""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.theme import Theme

from ..ai.backends import resolve_embedder
from ..ai.classify import AiInteraction, CreativeClassifier, EmbeddingClassifier
from ..ai.ollama import OllamaClient
from ..core import detect
from ..core.collect import collect_files
from ..core.conflict import ConflictStrategy
from ..core.config import load_ruleset
from ..core.dedupe import apply_dedupe, find_duplicates
from ..core.engine import Interaction, UnknownDecision, sort_files
from ..core.events import FilePlanned, FileSkipped, Progress as ProgressEvent, ScanStarted
from ..core.history import HistoryStore
from ..core.manifest import MoveRecord
from ..core.organize import Scheme
from ..core.runlog import log_run
from ..core.stats import compute_stats
from ..core.watch import Watcher

CUSTOM_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "theme": "magenta",
    "category": "blue",
    "dry": "italic dim white",
})

console = Console(theme=CUSTOM_THEME)


# ─── INTERACTIVE PROMPTS ────────────────────────────────────────────────────

class RichInteraction(Interaction):
    """Interactive decisions via Rich prompts (``--interactive`` mode)."""

    def confirm_theme(self, file: Path, theme: str) -> bool:
        return Confirm.ask(
            f"[info]Group files of theme '[theme]{theme}[/theme]' together?[/info]",
            default=True, console=console,
        )

    def handle_unknown(self, file: Path) -> UnknownDecision:
        console.print(f"  [bold]o[/bold]: others, [bold]s[/bold]: skip, [bold]n[/bold]: new category")
        choice = Prompt.ask(
            f"[info]'{file.name}' is unrecognised. What now?[/info]",
            choices=["o", "s", "n"], console=console,
        )
        if choice == "s":
            return UnknownDecision(action="skip")
        if choice == "n":
            name = Prompt.ask("  [info]New category name[/info]", console=console).strip().upper()
            if name:
                return UnknownDecision(action="category", category=name)
        return UnknownDecision(action="others")

    def resolve_conflict(self, target: Path, default: ConflictStrategy) -> ConflictStrategy:
        console.print(
            f"  [warning]⚠ CONFLICT[/warning] [bold]{target.name}[/bold] already exists in "
            f"[category]{target.parent.name}[/category]"
        )
        console.print("  [bold]r[/bold]: rename, [bold]s[/bold]: skip, [bold]o[/bold]: overwrite")
        choice = Prompt.ask("[info]Action?[/info]", choices=["r", "s", "o"], console=console)
        return {
            "r": ConflictStrategy.RENAME,
            "s": ConflictStrategy.SKIP,
            "o": ConflictStrategy.OVERWRITE,
        }[choice]


# ─── ARGUMENT PARSING ───────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup",
        description="Sort a directory's files by type (content/MIME detection + extension fallback).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  cleanup ~/Downloads
  cleanup ~/Downloads --dry-run
  cleanup ~/Downloads --extensions py js ts --conflict skip
  cleanup ~/Downloads --recursive --conflict rename
  cleanup ~/Downloads --smart --interactive
  cleanup ~/Downloads --ai            # zero-shot embeddings (fixed categories)
  cleanup ~/Downloads --ai-creative   # generative LLM (can invent categories)
  cleanup ~/Downloads --by date
  cleanup ~/Downloads --watch         # sort new files as they arrive
  cleanup ~/Downloads --dedupe report --recursive
  cleanup ~/Downloads --undo        # multi-level
  cleanup ~/Downloads --redo
        """,
    )
    parser.add_argument("directory", type=Path, help="Directory to sort")
    parser.add_argument("--extensions", "-e", nargs="+", metavar="EXT",
                        help="Only sort these extensions (e.g. py js png)")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Descend into subdirectories")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Watch the directory and sort new files continuously (Ctrl+C to stop)")
    parser.add_argument("--interval", type=float, default=2.0, metavar="SEC",
                        help="Polling interval for --watch (default: 2.0s)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview moves without executing them")
    parser.add_argument("--conflict", "-c", choices=[s.value for s in ConflictStrategy],
                        default=ConflictStrategy.RENAME.value,
                        help="Duplicate-name behaviour (default: rename)")
    parser.add_argument("--by", "-b", choices=[s.value for s in Scheme],
                        default=Scheme.TYPE.value,
                        help="Folder layout: type, date (YYYY/MM), or size bucket")
    parser.add_argument("--smart", "-s", action="store_true",
                        help="Enable contextual theme grouping (Smart Tags)")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Ask for confirmation on themes, unknowns and conflicts")
    parser.add_argument("--ai", action="store_true",
                        help="Categorize ambiguous files by embedding similarity (deterministic, "
                             "needs an embedding model like nomic-embed-text)")
    parser.add_argument("--ai-creative", action="store_true",
                        help="Use a generative LLM that can invent new categories (vs. embeddings)")
    parser.add_argument("--ai-adaptive", action="store_true",
                        help="Learn from your corrections: reuse a remembered category for similar files")
    parser.add_argument("--ai-teach", nargs=2, metavar=("FILE", "CATEGORY"),
                        help="Teach the adaptive AI that FILE belongs in CATEGORY, then exit")
    parser.add_argument("--ai-backend", choices=["auto", "local", "ollama"], default="auto",
                        help="Embedding backend for --ai: local (in-process, no server), "
                             "ollama, or auto (default: prefer local)")
    parser.add_argument("--ai-model", metavar="MODEL",
                        help="Ollama model for --ai-creative / ollama backend (default: auto-detect)")
    parser.add_argument("--clean-empty", action="store_true",
                        help="Remove empty subdirectories after sorting")
    parser.add_argument("--no-trash", action="store_true",
                        help="Hard-delete on overwrite/dedupe instead of using the OS trash")
    parser.add_argument("--dedupe", nargs="?", const="report",
                        choices=["report", "move", "trash"], metavar="ACTION",
                        help="Find duplicate files by content; ACTION: report (default), move, trash")
    parser.add_argument("--stats", action="store_true",
                        help="Show a summary of the directory (categories, sizes, duplicates)")
    parser.add_argument("--undo", "-u", action="store_true",
                        help="Roll back the last sort (multi-level)")
    parser.add_argument("--redo", action="store_true",
                        help="Re-apply the last undone sort")
    return parser


# ─── RENDERING ──────────────────────────────────────────────────────────────

def _print_summary(manifest: list[MoveRecord]) -> None:
    if not manifest:
        return
    table = Table(title="Operation summary", box=None)
    table.add_column("File", style="cyan")
    table.add_column("Theme", style="magenta")
    table.add_column("Category", style="blue")
    table.add_column("Status", style="green")
    for record in manifest[:15]:
        table.add_row(Path(record.src).name, record.theme or "-", record.category, "Moved")
    if len(manifest) > 15:
        table.add_row(f"... and {len(manifest) - 15} more files", "", "", "")
    console.print("\n")
    console.print(table)


def _run_sort(args: argparse.Namespace, directory: Path) -> None:
    ruleset, message = load_ruleset(directory)
    if message:
        style = "success" if message.startswith("Config") else "warning"
        console.print(f"  [{style}]{message}[/{style}]")

    filter_exts = {e.lstrip(".").lower() for e in args.extensions} if args.extensions else None
    files = collect_files(
        directory, ruleset,
        recursive=args.recursive,
        filter_exts=filter_exts,
        should_enter_project=(_ask_enter_project if args.interactive else None),
        on_permission_error=lambda p: console.print(
            f"  [warning]⚠[/warning] Permission denied for [bold]{p}[/bold]"),
    )

    if not files:
        console.print("\n  [info]ℹ No files to sort.[/info]")
        return

    console.print(f"\n  [bold]{len(files)}[/bold] file(s) detected")
    if not detect.CONTENT_DETECTION:
        console.print("  [dim]• content detection off (libmagic unavailable) — using extensions[/dim]")
    if args.recursive:   console.print("  [dim]• recursive mode[/dim]")
    if args.by != Scheme.TYPE.value:
        console.print(f"  [dim]• layout: {args.by}[/dim]")
    if args.dry_run:     console.print("  [warning]• ⚠ DRY-RUN — simulation only[/warning]")
    if args.smart:       console.print("  [magenta]• 🧠 Smart Tags on[/magenta]")
    if args.interactive: console.print("  [cyan]• 🤝 interactive mode[/cyan]")

    interaction = RichInteraction() if args.interactive else None
    if args.ai or args.ai_creative:
        interaction = _build_ai_interaction(args, ruleset, interaction)
    console.print()

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TaskProgressColumn(), TimeRemainingColumn(),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("Processing...", total=len(files))

        def on_event(event) -> None:
            if isinstance(event, ScanStarted):
                progress.update(task, total=event.total)
            elif isinstance(event, FilePlanned):
                rel_src = _safe_relpath(event.src, directory)
                rel_dest = _safe_relpath(event.dest, directory)
                if event.dry_run:
                    console.print(f"  [dry]DRY-RUN[/dry]  {rel_src} [bold]→[/bold] [category]{rel_dest}[/category]")
            elif isinstance(event, FileSkipped) and args.dry_run:
                console.print(f"  [error]SKIPPED[/error]  {_safe_relpath(event.src, directory)}")
            elif isinstance(event, ProgressEvent):
                progress.update(task, completed=event.done)

        manifest = sort_files(
            directory, files, ruleset,
            conflict_strategy=ConflictStrategy(args.conflict),
            dry_run=args.dry_run,
            smart=args.smart,
            scheme=Scheme(args.by),
            use_trash=not args.no_trash,
            interaction=interaction,
            on_event=on_event,
        )

    if not args.dry_run and manifest:
        HistoryStore(directory).record(f"sort by {args.by}", manifest)
        _print_summary(manifest)
        log_run(directory, f"sort ({args.by}): moved {len(manifest)} file(s)")

    if args.clean_empty and not args.dry_run:
        removed = _clean_empty_dirs(directory, ruleset.managed_dirs)
        if removed:
            console.print(f"  [dim]• removed {removed} empty folder(s)[/dim]")

    status = "[italic]simulated[/italic]" if args.dry_run else "[bold success]moved[/bold success]"
    count = len(files) if args.dry_run else len(manifest)
    console.print(f"\n  [bold success]✨ Done[/bold success] — {count} file(s) {status}.")


def _ask_enter_project(folder: Path) -> bool:
    # Returning True means "enter/sort it"; prompt is phrased as "ignore?".
    ignore = Confirm.ask(
        f"[info]Folder '{folder.name}' looks like a project. Ignore it?[/info]",
        default=True, console=console,
    )
    return not ignore


def _run_watch(args: argparse.Namespace, directory: Path) -> None:
    ruleset, message = load_ruleset(directory)
    if message:
        style = "success" if message.startswith("Config") else "warning"
        console.print(f"  [{style}]{message}[/{style}]")

    filter_exts = {e.lstrip(".").lower() for e in args.extensions} if args.extensions else None
    interaction = None
    if args.ai or args.ai_creative:
        interaction = _build_ai_interaction(args, ruleset, None)

    opts = []
    if args.recursive: opts.append("recursive")
    if args.smart: opts.append("🧠 smart")
    if args.by != Scheme.TYPE.value: opts.append(f"layout {args.by}")
    if interaction is not None: opts.append("🤖 AI")
    detail = f" · {', '.join(opts)}" if opts else ""

    console.print(Panel.fit(
        f"[bold cyan]👀 Watching[/bold cyan] [bold]{directory}[/bold]\n"
        f"[dim]polling every {args.interval:g}s{detail} — Ctrl+C to stop[/dim]",
        border_style="cyan",
    ))
    if not detect.CONTENT_DETECTION:
        console.print("  [dim]• content detection off (libmagic unavailable)[/dim]")

    counters = {"total": 0}

    def on_event(event) -> None:
        if isinstance(event, FilePlanned):
            ts = datetime.now().strftime("%H:%M:%S")
            console.print(f"  [dim]{ts}[/dim]  {_safe_relpath(event.src, directory)} "
                         f"[bold]→[/bold] [category]{_safe_relpath(event.dest, directory)}[/category]")

    def on_sorted(manifest) -> None:
        counters["total"] += len(manifest)
        log_run(directory, f"watch: sorted {len(manifest)} file(s)")

    watcher = Watcher(
        directory, ruleset,
        recursive=args.recursive, filter_exts=filter_exts,
        conflict=ConflictStrategy(args.conflict), smart=args.smart,
        scheme=Scheme(args.by), use_trash=not args.no_trash,
        interaction=interaction, poll_interval=args.interval,
        on_event=on_event, on_sorted=on_sorted,
    )
    # Stop cleanly on Ctrl+C (SIGINT) and on `kill` (SIGTERM, e.g. launchd/systemd).
    # Explicit handlers also override an inherited SIG_IGN on backgrounded jobs.
    previous: dict[int, object] = {}

    def _stop(_signum, _frame):
        watcher.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass  # e.g. not in the main thread

    try:
        watcher.run()
    except KeyboardInterrupt:
        watcher.stop()
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    console.print(f"\n  [bold success]✨ Watch stopped[/bold success] "
                 f"— {counters['total']} file(s) sorted this session.")


def _maybe_adaptive(args, classifier, embedder):
    """Wrap ``classifier`` with adaptive memory when ``--ai-adaptive`` is set."""
    if not args.ai_adaptive:
        return classifier
    emb = embedder
    if emb is None:
        emb, _, _ = resolve_embedder("auto")
    if emb is None:
        console.print("  [warning]• 🧠 adaptive needs an embedding backend — using base AI[/warning]")
        return classifier
    from ..ai.adaptive import AdaptiveClassifier
    from ..ai.memory import DecisionStore
    store = DecisionStore()
    console.print(f"  [cyan]• 🧠 adaptive on ({len(store)} learned decision(s))[/cyan]")
    return AdaptiveClassifier(emb, classifier, store)


def _run_teach(args: argparse.Namespace, directory: Path) -> None:
    file_arg, category = args.ai_teach
    target = Path(file_arg)
    if not target.is_absolute():
        target = directory / file_arg
    if not target.is_file():
        console.print(f"[error]❌ '{target}' is not a file.[/error]")
        sys.exit(1)

    embedder, _threshold, label = resolve_embedder(args.ai_backend, ollama_model=args.ai_model)
    if embedder is None:
        console.print(f"[error]❌ {label}[/error]")
        sys.exit(1)

    from ..ai.adaptive import AdaptiveClassifier
    from ..ai.memory import DecisionStore
    store = DecisionStore()
    adaptive = AdaptiveClassifier(embedder, EmbeddingClassifier(embedder), store)
    category = category.strip().upper()
    if adaptive.record(target, category):
        console.print(f"  [success]✔ Learned:[/success] [cyan]{target.name}[/cyan] "
                     f"[bold]→[/bold] [category]{category}[/category] "
                     f"[dim]({len(store)} decision(s) remembered)[/dim]")
    else:
        console.print("[error]❌ Could not embed the file (no backend?).[/error]")
        sys.exit(1)


def _build_ai_interaction(args, ruleset, base):
    """Wrap ``base`` with an AI classifier, or fall back if unavailable.

    Default (``--ai``): deterministic embedding similarity over a fixed category
    list, running either in-process (local) or via Ollama.
    ``--ai-creative``: a generative LLM (Ollama) that may invent categories.
    """
    if args.ai_creative:
        client = OllamaClient(model=args.ai_model)
        if not client.available() or not client.resolve_model():
            console.print("  [warning]• 🤖 --ai-creative needs Ollama with a generative model "
                         "— continuing without AI[/warning]")
            return base
        classifier = CreativeClassifier(client, list(ruleset.mime_categories.keys()))
        console.print(f"  [cyan]• 🤖 AI creative mode (LLM: {client.model})[/cyan]")
        classifier = _maybe_adaptive(args, classifier, None)
        return AiInteraction(classifier, wrap=base or None)

    # Default --ai: embedding similarity via the resolved backend.
    embedder, threshold, label = resolve_embedder(args.ai_backend, ollama_model=args.ai_model)
    if embedder is None:
        console.print(f"  [warning]• 🤖 {label} — continuing without AI[/warning]")
        return base
    classifier = EmbeddingClassifier(embedder, threshold=threshold)
    console.print(f"  [cyan]• 🤖 AI zero-shot embeddings — {label}[/cyan]")
    classifier = _maybe_adaptive(args, classifier, embedder)
    return AiInteraction(classifier, wrap=base or None)


def _run_stats(directory: Path) -> None:
    ruleset, _ = load_ruleset(directory)
    with console.status("[info]Analyzing…[/info]"):
        stats = compute_stats(directory, ruleset)

    if stats.total_files == 0:
        console.print("\n  [info]ℹ Empty directory.[/info]")
        return

    console.print(Panel.fit(
        f"[bold]{stats.total_files}[/bold] files · [bold]{_format_bytes(stats.total_size)}[/bold]"
        + (f"\n[warning]{stats.duplicate_groups} duplicate group(s) · "
           f"{_format_bytes(stats.reclaimable)} reclaimable[/warning]"
           if stats.duplicate_groups else ""),
        title="📊 Insights", border_style="blue",
    ))

    # Category breakdown with size bars.
    max_size = max((c.size for c in stats.categories), default=1) or 1
    table = Table(title="By category", box=None)
    table.add_column("Category", style="blue")
    table.add_column("Files", justify="right", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("", style="magenta")
    for c in stats.categories:
        bar = "█" * max(1, round(c.size / max_size * 24)) if c.size else ""
        table.add_row(c.category, str(c.count), _format_bytes(c.size), bar)
    console.print("\n")
    console.print(table)

    # Largest files.
    if stats.largest:
        big = Table(title="Largest files", box=None)
        big.add_column("File", style="cyan")
        big.add_column("Size", justify="right", style="magenta")
        for rel, size in stats.largest[:8]:
            big.add_row(rel, _format_bytes(size))
        console.print("\n")
        console.print(big)

    # Activity by month.
    if stats.by_month:
        max_m = max(stats.by_month.values()) or 1
        console.print("\n  [bold]Files by month[/bold]")
        for month, count in stats.by_month.items():
            bar = "▉" * max(1, round(count / max_m * 30))
            console.print(f"  [dim]{month}[/dim]  [blue]{bar}[/blue] {count}")


def _run_undo(directory: Path) -> None:
    ruleset, _ = load_ruleset(directory)
    store = HistoryStore(directory)
    if not store.can_undo:
        console.print("[error]❌ Nothing to undo.[/error]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Undoing...", total=1)
        result = store.undo(
            ruleset.managed_dirs,
            on_progress=lambda done, total: progress.update(task, completed=done, total=total),
        )

    label = result.session.label if result.session else "?"
    console.print(f"\n  [success]✔ Undone '[bold]{label}[/bold]' — {result.restored} file(s) restored.[/success]")
    if result.missing:
        console.print(f"  [warning]⚠ {len(result.missing)} file(s) were missing during rollback.[/warning]")
    if store.can_undo:
        console.print(f"  [dim]• {len(store.undo_stack())} earlier run(s) still undoable[/dim]")
    log_run(directory, f"undo '{label}': {result.restored} restored")


def _run_redo(directory: Path) -> None:
    store = HistoryStore(directory)
    if not store.can_redo:
        console.print("[error]❌ Nothing to redo.[/error]")
        sys.exit(1)

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), console=console, transient=True,
    ) as progress:
        task = progress.add_task("Redoing...", total=1)
        result = store.redo(
            on_progress=lambda done, total: progress.update(task, completed=done, total=total),
        )

    label = result.session.label if result.session else "?"
    console.print(f"\n  [success]✔ Redone '[bold]{label}[/bold]' — {result.restored} file(s) re-applied.[/success]")
    log_run(directory, f"redo '{label}': {result.restored} re-applied")


def _run_dedupe(args: argparse.Namespace, directory: Path) -> None:
    ruleset, _ = load_ruleset(directory)
    files = collect_files(
        directory, ruleset,
        recursive=args.recursive,
        include_managed=True,
        on_permission_error=lambda p: console.print(
            f"  [warning]⚠[/warning] Permission denied for [bold]{p}[/bold]"),
    )
    with console.status("[info]Hashing files...[/info]"):
        groups = find_duplicates(files)

    if not groups:
        console.print("\n  [success]✔ No duplicate files found.[/success]")
        return

    wasted = sum(g.wasted_bytes for g in groups)
    table = Table(title=f"Duplicate groups ({len(groups)}) — {_format_bytes(wasted)} reclaimable", box=None)
    table.add_column("Size", style="blue", justify="right")
    table.add_column("Copies", style="yellow", justify="right")
    table.add_column("Files (first is kept)", style="cyan")
    for group in groups[:20]:
        names = "  ·  ".join(_safe_relpath(p, directory) for p in group.paths)
        table.add_row(_format_bytes(group.size), str(len(group.paths)), names)
    if len(groups) > 20:
        table.add_row("", "", f"... and {len(groups) - 20} more groups")
    console.print("\n")
    console.print(table)

    action = args.dedupe
    if action == "report":
        console.print("\n  [dim]Re-run with --dedupe move or --dedupe trash to act on these.[/dim]")
        return

    verb = "move to DUPLICATES/" if action == "move" else "send to the OS trash"
    if not Confirm.ask(f"\n[warning]{verb.capitalize()} the extra copies?[/warning]", default=False, console=console):
        console.print("  [dim]Cancelled.[/dim]")
        return

    result = apply_dedupe(directory, groups, action=action, use_trash=not args.no_trash)
    if result.moved:
        HistoryStore(directory).record("dedupe move", result.moved)
        console.print(f"\n  [success]✔ Moved {len(result.moved)} duplicate(s) to DUPLICATES/ (undoable).[/success]")
        log_run(directory, f"dedupe move: {len(result.moved)} file(s)")
    if result.trashed:
        console.print(f"\n  [success]✔ Sent {result.trashed} duplicate(s) to the trash.[/success]")
        log_run(directory, f"dedupe trash: {result.trashed} file(s)")
    if result.failed:
        console.print(f"  [warning]⚠ {len(result.failed)} file(s) could not be removed "
                     f"(trash unavailable? try without --no-trash).[/warning]")


def _clean_empty_dirs(directory: Path, managed_dirs: set[str]) -> int:
    """Remove empty subdirectories (deepest first), leaving the root intact."""
    removed = 0
    for sub in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if sub.is_dir() and not any(sub.iterdir()):
            try:
                sub.rmdir()
                removed += 1
            except OSError:
                pass
    return removed


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _safe_relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    directory = args.directory.resolve()

    if not directory.is_dir():
        console.print(f"[error]❌ ERROR: '{directory}' is not a valid directory.[/error]")
        sys.exit(1)

    console.print(Panel.fit(
        "[bold cyan]✨ CleanUp ✨[/bold cyan]\n[italic]Intelligent, content-aware file sorting[/italic]",
        border_style="blue",
    ))

    if args.ai_teach:
        _run_teach(args, directory)
    elif args.stats:
        _run_stats(directory)
    elif args.undo:
        _run_undo(directory)
    elif args.redo:
        _run_redo(directory)
    elif args.dedupe:
        _run_dedupe(args, directory)
    elif args.watch:
        if args.dry_run:
            console.print("[error]❌ --watch cannot be combined with --dry-run.[/error]")
            sys.exit(1)
        _run_watch(args, directory)
    else:
        _run_sort(args, directory)


if __name__ == "__main__":
    main()
