"""File category and theme detection.

Detection strategy (best signal first):

1. **Content sniffing** — read the file's magic bytes via ``libmagic``
   (``python-magic``). This is authoritative for binary formats and catches
   files whose extension lies (a ``.txt`` that is really a JPEG).
2. **Extension MIME guess** — ``mimetypes.guess_type``. libmagic reports plain
   text as ``text/plain`` for source code, config, CSV, etc., so for textual /
   ambiguous content we prefer the extension-based guess, which distinguishes
   ``text/x-python`` (SCRIPTS) from ``text/plain`` (TEXTS).
3. **Extension fallback table** — the ``Ruleset.ext_fallback`` map.
4. ``OTHERS``.

If ``python-magic``/libmagic is unavailable the sniffing step is skipped and
detection degrades cleanly to steps 2–4 (the pre-existing behaviour).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .config import OTHERS, Ruleset

# MIME values that carry no category information on their own — when content
# sniffing returns one of these we defer to the extension-based signal.
_AMBIGUOUS_MIMES = frozenset({
    "text/plain",
    "application/octet-stream",
    "inode/x-empty",
    "application/x-empty",
})

# ─── libmagic (optional) ────────────────────────────────────────────────────

try:  # pragma: no cover - import wiring
    import magic as _magic

    try:
        _MAGIC = _magic.Magic(mime=True)
        CONTENT_DETECTION = True
    except Exception:  # libmagic present as a module but lib not loadable
        _MAGIC = None
        CONTENT_DETECTION = False
except Exception:
    _magic = None
    _MAGIC = None
    CONTENT_DETECTION = False


def sniff_mime(path: Path) -> str | None:
    """Return the MIME type from the file's actual bytes, or ``None`` if
    content detection is unavailable or fails."""
    if _MAGIC is None:
        return None
    try:
        return _MAGIC.from_file(str(path))
    except (OSError, ValueError):
        return None


# ─── CATEGORY ───────────────────────────────────────────────────────────────

def detect_category(path: Path, ruleset: Ruleset) -> str:
    """Classify ``path`` into one of the ruleset categories, or ``OTHERS``."""
    content_mime = sniff_mime(path)
    guessed_mime, _ = mimetypes.guess_type(str(path))

    # Prefer real content, but fall back to the extension guess when the sniffed
    # type is uninformative (plain text, generic binary, empty file).
    if content_mime and content_mime not in _AMBIGUOUS_MIMES:
        mime = content_mime
    else:
        mime = guessed_mime or content_mime

    if mime:
        for category, predicate in ruleset.mime_categories.items():
            if predicate(mime):
                return category

    ext = path.suffix.lstrip(".").lower()
    if ext:
        for category, extensions in ruleset.ext_fallback.items():
            if ext in extensions:
                return category

    return OTHERS


# ─── THEME ────────────────────────────────────────────────────────────────────

def detect_theme(path: Path, ruleset: Ruleset) -> str | None:
    """Detect a Smart-Tag theme from keywords in the file name or its parent
    folder names. Returns the first matching theme, or ``None``."""
    if not ruleset.themes:
        return None
    search_space = (path.name + " " + " ".join(path.parts)).lower()
    for theme, keywords in ruleset.themes.items():
        if any(keyword in search_space for keyword in keywords):
            return theme
    return None
