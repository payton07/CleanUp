"""``.cleanupignore`` — gitignore-style exclusions.

One glob per line; blank lines and ``#`` comments are skipped. A pattern matches
against a file/dir name and its path relative to the target directory, so both
``*.tmp`` and ``build/`` work.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

IGNORE_FILE = ".cleanupignore"


def load_ignore_patterns(directory: Path) -> list[str]:
    path = directory / IGNORE_FILE
    if not path.exists():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(relpath: str, name: str, patterns: list[str]) -> bool:
    """True if ``name`` or ``relpath`` matches any ignore pattern."""
    relpath = relpath.replace("\\", "/")
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if (fnmatch.fnmatch(name, pat)
                or fnmatch.fnmatch(relpath, pat)
                or fnmatch.fnmatch(relpath, pat + "/*")):
            return True
    return False
