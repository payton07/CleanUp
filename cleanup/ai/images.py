"""Content-based image sub-sorting (zero-shot CLIP).

Sorts files already in ``IMAGES`` into visual sub-types — screenshots, photos,
memes, documents, … — by embedding each image with CLIP and comparing it to
text descriptions of the categories (they share one embedding space). Runs
in-process via ``fastembed`` (optional ``[image]`` extra); if unavailable the
feature degrades and images stay in ``IMAGES``.
"""

from __future__ import annotations

import os
from pathlib import Path

from .classify import _cosine, Classifier  # noqa: F401  (Classifier documents the shape)
from ..core.engine import Interaction, UnknownDecision

IMAGE_CATEGORY = "IMAGES"

_VISION_MODEL = "Qdrant/clip-ViT-B-32-vision"
_TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"

# CLIP image↔text cosines sit on a low scale (~0.2–0.3); below this the image
# stays in IMAGES rather than being forced into a sub-type.
DEFAULT_IMAGE_THRESHOLD = float(os.environ.get("CLEANUP_AI_IMAGE_THRESHOLD", "0.19"))

# Sub-category → CLIP text prompt.
DEFAULT_IMAGE_CATEGORIES: dict[str, str] = {
    "SCREENSHOTS": "a screenshot of a computer screen, phone screen, app UI, or website",
    "PHOTOS":      "a photograph of people, animals, nature, food, or a real-world scene",
    "MEMES":       "an internet meme, a funny image with large caption text",
    "DOCUMENTS":   "a scanned paper document, receipt, invoice, or a page full of text",
    "DIAGRAMS":    "a chart, graph, diagram, or technical illustration",
    "ART":         "a digital illustration, drawing, painting, or artwork",
}


class ImageEmbedder:
    """Embeds images and text into the shared CLIP space via fastembed."""

    def __init__(self, vision_model: str = _VISION_MODEL, text_model: str = _TEXT_MODEL):
        self.vision_model = vision_model
        self.text_model = text_model
        self._vision = None
        self._text = None

    @staticmethod
    def available() -> bool:
        try:
            import fastembed  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure(self) -> bool:
        if self._vision is not None and self._text is not None:
            return True
        try:
            from fastembed import ImageEmbedding, TextEmbedding
            self._vision = ImageEmbedding(model_name=self.vision_model)
            self._text = TextEmbedding(model_name=self.text_model)
            return True
        except Exception:
            self._vision = self._text = None
            return False

    def embed_image(self, path: Path) -> list[float] | None:
        if not self._ensure():
            return None
        try:
            return next(iter(self._vision.embed([str(path)]))).tolist()
        except Exception:
            return None

    def embed_text(self, text: str) -> list[float] | None:
        if not self._ensure():
            return None
        try:
            return next(iter(self._text.embed([text]))).tolist()
        except Exception:
            return None


class ImageClassifier:
    """Nearest CLIP sub-category for an image (or None below the threshold)."""

    def __init__(
        self,
        embedder: ImageEmbedder,
        categories: dict[str, str] | None = None,
        threshold: float = DEFAULT_IMAGE_THRESHOLD,
    ):
        self._embedder = embedder
        self._categories = categories or DEFAULT_IMAGE_CATEGORIES
        self._threshold = threshold
        self._labels: dict[str, list[float]] | None = None

    def _ensure_labels(self) -> None:
        if self._labels is not None:
            return
        self._labels = {}
        for name, prompt in self._categories.items():
            vec = self._embedder.embed_text(prompt)
            if vec:
                self._labels[name] = vec

    def classify(self, path: Path) -> str | None:
        self._ensure_labels()
        if not self._labels:
            return None
        vec = self._embedder.embed_image(path)
        if not vec:
            return None
        best, score = max(
            ((name, _cosine(vec, lv)) for name, lv in self._labels.items()),
            key=lambda pair: pair[1],
        )
        return best if score >= self._threshold else None


class ImageInteraction(Interaction):
    """Refines ``IMAGES`` into ``IMAGES/<sub-type>`` using a CLIP classifier.

    Wraps another :class:`Interaction`: non-image categories (and all theme /
    conflict / unknown decisions) pass through unchanged, so this composes with
    the text ``AiInteraction``.
    """

    def __init__(self, classifier: ImageClassifier, wrap: Interaction | None = None):
        self._classifier = classifier
        self._wrap = wrap or Interaction()
        self.subsorted: dict[str, str] = {}

    def refine_category(self, file: Path, category: str) -> str:
        if category == IMAGE_CATEGORY:
            sub = self._classifier.classify(file)
            if sub:
                self.subsorted[str(file)] = sub
                return f"{IMAGE_CATEGORY}/{sub}"
            return category
        return self._wrap.refine_category(file, category)

    def confirm_theme(self, file: Path, theme: str) -> bool:
        return self._wrap.confirm_theme(file, theme)

    def handle_unknown(self, file: Path) -> UnknownDecision:
        return self._wrap.handle_unknown(file)

    def resolve_conflict(self, target, default):
        return self._wrap.resolve_conflict(target, default)
