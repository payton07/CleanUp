"""Adaptive classifier — learns from user corrections.

Wraps a base classifier (embedding or creative) with a memory of past
corrections. On each file it first embeds the content and looks for a very
similar remembered decision; if found (cosine >= the adapt threshold) that
learned category wins. Otherwise it defers to the base classifier.

Corrections are captured by the UI (web preview override, CLI prompt) which
calls :meth:`record`.
"""

from __future__ import annotations

import os
from pathlib import Path

from .classify import Classifier, file_repr
from .memory import DecisionStore

# How similar a new file must be to a past correction to reuse its category.
# High by design: only near-identical documents inherit a learned decision.
DEFAULT_ADAPT_THRESHOLD = float(os.environ.get("CLEANUP_AI_ADAPT_THRESHOLD", "0.85"))


class _Embedder:
    def embed(self, text: str, model: str | None = None) -> list[float] | None: ...


class AdaptiveClassifier:
    def __init__(
        self,
        embedder: _Embedder,
        base: Classifier,
        store: DecisionStore | None = None,
        adapt_threshold: float = DEFAULT_ADAPT_THRESHOLD,
    ):
        self._embedder = embedder
        self._base = base
        # NB: DecisionStore defines __len__, so an empty store is falsy — must
        # test `is not None`, not `store or ...`, or the passed store is dropped.
        self._store = store if store is not None else DecisionStore()
        self._threshold = adapt_threshold

    def classify(self, path: Path, current_category: str) -> str | None:
        if len(self._store):
            vec = self._embedder.embed(file_repr(path))
            if vec:
                match = self._store.nearest(vec)
                if match and match[1] >= self._threshold:
                    return match[0]
        return self._base.classify(path, current_category)

    def record(self, path: Path, category: str) -> bool:
        """Remember a user's correction for this file. Returns False if the file
        could not be embedded."""
        vec = self._embedder.embed(file_repr(path))
        if not vec:
            return False
        self._store.add(vec, category)
        return True
