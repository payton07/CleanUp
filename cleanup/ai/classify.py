"""AI classification of ambiguous files.

When rule-based detection leaves a file in a generic bucket (``TEXTS`` or
``OTHERS``), an AI *classifier* may propose a more specific category from the
file name and a short content preview. Two strategies share one interface:

- :class:`EmbeddingClassifier` (default) — encodes the file and each candidate
  category with an embedding model and picks the nearest by cosine similarity.
  Deterministic, and can only ever return a name from the fixed list.
- :class:`CreativeClassifier` — a generative LLM that may invent new category
  names. Slower; opt-in via ``--ai-creative``.

Everything is local (Ollama) and opt-in.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Protocol

from ..core.engine import Interaction, UnknownDecision

# Cosine cut for accepting an embedding match. Calibrated on a labeled corpus
# (see scripts/calibrate_threshold.py) with nomic-embed-text: correct matches
# scored >= 0.564, unrelated text <= 0.558, so 0.56 separates them. A rejection
# is a safe no-op (the file stays in TEXTS). Override via CLEANUP_AI_THRESHOLD.
DEFAULT_THRESHOLD = float(os.environ.get("CLEANUP_AI_THRESHOLD", "0.56"))

_SNIPPET_BYTES = 1200
_MAX_CATEGORY_LEN = 24
_CATEGORY_RE = re.compile(r"[^A-Z0-9_]")

_SYSTEM = (
    "You are a file-organizing assistant. Given a file, reply with the single "
    "best folder name to file it under. Reuse one of the existing categories if "
    "it fits; otherwise invent a short UPPERCASE name (letters and underscores "
    "only). Reply with ONLY the folder name, no punctuation or explanation."
)

# Semantic targets for zero-shot embedding classification. Each entry maps a
# folder name to a short description whose embedding represents the category.
DEFAULT_AI_CATEGORIES: dict[str, str] = {
    "INVOICES":  "invoice, bill, amount due, payment, receipt",
    "REPORTS":   "report, analysis, summary, findings, quarterly results",
    "CONTRACTS": "contract, agreement, terms, signature, legal clause",
    "LETTERS":   "letter, correspondence, dear, sincerely, regards",
    "RESUMES":   "resume, cv, curriculum vitae, work experience, skills",
    "NOTES":     "notes, memo, todo, reminder, ideas, meeting minutes",
    "LOGS":      "log, timestamp, error, warning, debug, stack trace",
    "CONFIG":    "configuration, settings, yaml, ini, environment variables",
    "DATA":      "dataset, csv, table, records, rows and columns",
    "RECIPES":   "recipe, ingredients, cooking steps, bake, oven",
    "EBOOKS":    "book, chapter, novel, story, ebook",
}


class _Generator(Protocol):
    def generate(self, prompt: str, system: str | None = None) -> str | None: ...


class _Embedder(Protocol):
    def embed(self, text: str, model: str | None = None) -> list[float] | None: ...


# ─── SHARED HELPERS ─────────────────────────────────────────────────────────

def read_snippet(path: Path, limit: int = _SNIPPET_BYTES) -> str:
    """Return a short textual preview, or a marker for binary/empty files."""
    try:
        raw = path.read_bytes()[:limit]
    except OSError:
        return "(unreadable)"
    if not raw:
        return "(empty file)"
    if b"\x00" in raw:
        return "(binary file)"
    text = raw.decode("utf-8", errors="replace")
    # Too many replacement chars → treat as binary.
    if text.count("�") > len(text) * 0.1:
        return "(binary file)"
    return text.strip()


def sanitize_category(text: str | None) -> str | None:
    """Coerce a raw model reply into a safe folder name, or None."""
    if not text or not text.strip():
        return None
    token = text.strip().splitlines()[0].strip().strip(".\"' `")
    token = token.upper().replace(" ", "_").replace("-", "_")
    token = _CATEGORY_RE.sub("", token)[:_MAX_CATEGORY_LEN].strip("_")
    return token or None


def classify_file(client: _Generator, path: Path, categories: list[str]) -> str | None:
    """Ask a generative model for the best category for ``path``. None on failure."""
    snippet = read_snippet(path)
    prompt = (
        f"Existing categories: {', '.join(categories)}\n"
        f"File name: {path.name}\n"
        f"Content preview:\n{snippet[:_SNIPPET_BYTES]}\n\n"
        f"Folder name:"
    )
    return sanitize_category(client.generate(prompt, system=_SYSTEM))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def file_repr(path: Path) -> str:
    """Canonical text used to embed a file (name + content preview). Shared by
    the embedding classifier and the adaptive memory so vectors are comparable."""
    return f"{path.name}\n{read_snippet(path)}"


# ─── CLASSIFIER STRATEGIES ──────────────────────────────────────────────────

class Classifier(Protocol):
    def classify(self, path: Path, current_category: str) -> str | None: ...


class CreativeClassifier:
    """Generative LLM strategy — may invent a new category (``--ai-creative``).

    Cached per file extension because generation is slow (~seconds); the
    trade-off is that two files sharing an extension get the same answer.
    """

    def __init__(self, client: _Generator, categories: list[str]):
        self._client = client
        self._categories = categories
        self._by_ext: dict[str, str | None] = {}

    def classify(self, path: Path, current_category: str) -> str | None:
        ext = path.suffix.lower()
        if ext and ext in self._by_ext:
            return self._by_ext[ext]
        result = classify_file(self._client, path, self._categories)
        if ext:
            self._by_ext[ext] = result
        return result


class EmbeddingClassifier:
    """Zero-shot strategy — nearest fixed category by cosine similarity.

    Deterministic and content-based, so it is evaluated *per file* (no
    extension cache): two ``.txt`` files may be an invoice and a recipe. Label
    embeddings are computed once and reused.
    """

    def __init__(
        self,
        client: _Embedder,
        categories: dict[str, str] | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self._client = client
        self._categories = categories or DEFAULT_AI_CATEGORIES
        self._threshold = threshold
        self._labels: dict[str, list[float]] | None = None

    def _ensure_labels(self) -> None:
        if self._labels is not None:
            return
        self._labels = {}
        for name, desc in self._categories.items():
            vec = self._client.embed(f"{name}: {desc}")
            if vec:
                self._labels[name] = vec

    def best_match(self, path: Path) -> tuple[str | None, float]:
        """Return the nearest category and its cosine score, ignoring the
        threshold. Useful for threshold calibration."""
        self._ensure_labels()
        if not self._labels:
            return None, 0.0
        vec = self._client.embed(file_repr(path))
        if not vec:
            return None, 0.0
        return max(
            ((name, _cosine(vec, label_vec)) for name, label_vec in self._labels.items()),
            key=lambda pair: pair[1],
        )

    def classify(self, path: Path, current_category: str) -> str | None:
        best, score = self.best_match(path)
        return best if best is not None and score >= self._threshold else None


# ─── INTERACTION ────────────────────────────────────────────────────────────

# Categories generic enough that AI is allowed to refine them into something
# more specific. Concrete types (IMAGES, VIDEOS, …) are left untouched.
DEFAULT_AMBIGUOUS = frozenset({"OTHERS", "TEXTS"})


class AiInteraction(Interaction):
    """Interaction that refines ambiguous categories via a :class:`Classifier`.

    Only files in an ambiguous bucket (``OTHERS`` / ``TEXTS``) are sent to the
    classifier; concrete categories pass through untouched. Wraps another
    :class:`Interaction` for theme/conflict/unknown decisions.
    """

    def __init__(
        self,
        classifier: Classifier,
        wrap: Interaction | None = None,
        ambiguous: frozenset[str] = DEFAULT_AMBIGUOUS,
    ):
        self._classifier = classifier
        self._wrap = wrap or Interaction()
        self._ambiguous = ambiguous
        # Records which files got an AI category (used by the web preview).
        self.suggested: dict[str, str] = {}

    def refine_category(self, file: Path, category: str) -> str:
        if category not in self._ambiguous:
            return category
        suggestion = self._classifier.classify(file, category)
        if suggestion and suggestion != category:
            self.suggested[str(file)] = suggestion
            return suggestion
        return category

    # Pass-through for the non-AI decisions.
    def confirm_theme(self, file: Path, theme: str) -> bool:
        return self._wrap.confirm_theme(file, theme)

    def handle_unknown(self, file: Path) -> UnknownDecision:
        return self._wrap.handle_unknown(file)

    def resolve_conflict(self, target, default):
        return self._wrap.resolve_conflict(target, default)
