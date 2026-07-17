"""Send files to the OS trash instead of deleting them outright.

Wraps ``send2trash`` so removals are recoverable. If the library is missing the
caller is told (returns ``False``) and can decide whether to proceed, rather
than silently hard-deleting.
"""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - import wiring
    from send2trash import send2trash as _send2trash
    TRASH_AVAILABLE = True
except Exception:
    _send2trash = None
    TRASH_AVAILABLE = False


def send_to_trash(path: Path) -> bool:
    """Move ``path`` to the OS trash. Returns True on success, False if trashing
    is unavailable or failed (the file is then left untouched)."""
    if _send2trash is None:
        return False
    try:
        _send2trash(str(path))
        return True
    except Exception:
        return False
