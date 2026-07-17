"""Append-only, human-readable run log (``.cleanup.log``).

One line per run so a user can audit what the tool did over time without
parsing the JSON history.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

LOG_FILE = ".cleanup.log"


def log_run(directory: Path, message: str) -> None:
    """Append a timestamped line to the directory's run log (best effort)."""
    line = f"{datetime.now().isoformat(timespec='seconds')}  {message}\n"
    try:
        with open(directory / LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass  # logging must never break a run
