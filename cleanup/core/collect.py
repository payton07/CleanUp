"""Discovery of the files to sort within a target directory."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import CONFIG_FILE, Ruleset
from .history import HISTORY_FILE
from .ignore import IGNORE_FILE, is_ignored, load_ignore_patterns
from .manifest import MANIFEST_FILE
from .runlog import LOG_FILE

_PROJECT_INDICATORS = {
    ".git", ".svn", "package.json", "pom.xml", "requirements.txt",
    "pyproject.toml", "venv", ".venv", ".vscode", "Makefile", "Cargo.toml",
}

# Files the tool owns and must never move.
_RESERVED_NAMES = {MANIFEST_FILE, CONFIG_FILE, HISTORY_FILE, LOG_FILE, IGNORE_FILE}


def is_project_folder(path: Path) -> bool:
    """True if ``path`` looks like a self-contained project (has a ``.git``,
    ``package.json``, ``venv``, …) that should not be broken apart."""
    if not path.is_dir():
        return False
    try:
        content = {p.name for p in path.iterdir()}
    except (PermissionError, OSError):
        return False
    return not _PROJECT_INDICATORS.isdisjoint(content)


def collect_files(
    directory: Path,
    ruleset: Ruleset,
    *,
    recursive: bool = False,
    filter_exts: set[str] | None = None,
    include_managed: bool = False,
    should_enter_project: Callable[[Path], bool] | None = None,
    on_permission_error: Callable[[Path], None] | None = None,
) -> list[Path]:
    """List the files to sort under ``directory``.

    In recursive mode, managed category/theme folders are skipped so a re-run
    does not re-sort already-sorted files — unless ``include_managed`` is set
    (used by dedupe, which must inspect already-sorted files too).
    ``should_enter_project`` is consulted for folders that look like projects;
    if it returns False (default) the folder is left untouched.
    """
    managed = ruleset.managed_dirs
    ignore_patterns = load_ignore_patterns(directory)

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(directory))
        except ValueError:
            return p.name

    def ignored(p: Path) -> bool:
        return bool(ignore_patterns) and is_ignored(_rel(p), p.name, ignore_patterns)

    def wanted(p: Path) -> bool:
        if p.name in _RESERVED_NAMES or ignored(p):
            return False
        if filter_exts is None:
            return True
        return p.suffix.lstrip(".").lower() in filter_exts

    if not recursive:
        try:
            return [p for p in directory.iterdir() if p.is_file() and wanted(p)]
        except (PermissionError, OSError):
            if on_permission_error:
                on_permission_error(directory)
            return []

    files: list[Path] = []

    def scan(current: Path) -> None:
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            if on_permission_error:
                on_permission_error(current)
            return
        for p in entries:
            if p.is_file():
                if wanted(p):
                    files.append(p)
            elif p.is_dir() and (include_managed or p.name not in managed):
                if ignored(p):
                    continue
                if is_project_folder(p):
                    if should_enter_project and should_enter_project(p):
                        scan(p)
                    # default: leave projects untouched
                else:
                    scan(p)

    scan(directory)
    return files
