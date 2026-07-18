"""Directory insights — a summary of what's in a folder.

Analyses the whole tree (including already-sorted category folders) and reports
totals, a per-category breakdown, the largest files, duplicate-reclaimable
space, and a by-month histogram. Pure data; the CLI and web render it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .collect import collect_files
from .config import Ruleset
from .dedupe import find_duplicates
from .detect import detect_category


@dataclass
class CategoryStat:
    category: str
    count: int
    size: int


@dataclass
class Stats:
    total_files: int = 0
    total_size: int = 0
    categories: list[CategoryStat] = field(default_factory=list)
    largest: list[tuple[str, int]] = field(default_factory=list)  # (relpath, size)
    duplicate_groups: int = 0
    reclaimable: int = 0
    by_month: dict[str, int] = field(default_factory=dict)         # "YYYY-MM" -> count


def compute_stats(
    directory: Path,
    ruleset: Ruleset,
    *,
    top: int = 10,
    include_duplicates: bool = True,
) -> Stats:
    """Compute insights for ``directory`` (recursively, including sorted dirs)."""
    files = collect_files(directory, ruleset, recursive=True, include_managed=True)

    stats = Stats()
    per_cat_count: dict[str, int] = defaultdict(int)
    per_cat_size: dict[str, int] = defaultdict(int)
    months: dict[str, int] = defaultdict(int)
    sized: list[tuple[str, int]] = []

    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        size = st.st_size
        category = detect_category(f, ruleset)

        stats.total_files += 1
        stats.total_size += size
        per_cat_count[category] += 1
        per_cat_size[category] += size

        month = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m")
        months[month] += 1

        try:
            rel = str(f.relative_to(directory))
        except ValueError:
            rel = f.name
        sized.append((rel, size))

    stats.categories = sorted(
        (CategoryStat(c, per_cat_count[c], per_cat_size[c]) for c in per_cat_count),
        key=lambda cs: cs.size,
        reverse=True,
    )
    stats.largest = sorted(sized, key=lambda pair: pair[1], reverse=True)[:top]
    stats.by_month = dict(sorted(months.items()))

    if include_duplicates:
        groups = find_duplicates(files)
        stats.duplicate_groups = len(groups)
        stats.reclaimable = sum(g.wasted_bytes for g in groups)

    return stats
