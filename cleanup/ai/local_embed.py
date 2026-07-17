"""In-process embedding backend (no external server).

Implements the same ``embed(text) -> vector`` contract as
:class:`cleanup.ai.ollama.OllamaClient`, but runs the model *inside* CleanUp via
``fastembed`` (ONNX, CPU, no PyTorch). The model (~130 MB) is downloaded once on
first use and cached, then works fully offline — no Ollama, no server.

``fastembed`` is an optional dependency (``pip install cleanup-cli[embed]``); if
it is absent this backend reports itself unavailable and the caller falls back.
"""

from __future__ import annotations

# Default embedding model — small, fast on CPU, good general-purpose quality.
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Cosine threshold calibrated for this model (scripts/calibrate_threshold.py
# --backend local): correct matches scored >= 0.569, so 0.56 keeps full coverage
# while rejecting clear junk. Override via CLEANUP_AI_THRESHOLD.
DEFAULT_THRESHOLD = 0.56


class LocalEmbedder:
    """Embeds text locally with fastembed. Lazy-loads the model on first use."""

    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL):
        self.model_name = model_name
        self.embed_model = model_name  # parity with OllamaClient attribute
        self._model = None  # loaded lazily

    @staticmethod
    def available() -> bool:
        """True if fastembed is importable (model may still download on first use)."""
        try:
            import fastembed  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name)
            return True
        except Exception:
            self._model = None
            return False

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        """Return the embedding vector for ``text``, or None on failure."""
        if not self._ensure_model():
            return None
        try:
            vec = next(iter(self._model.embed([text])))
            return vec.tolist()
        except Exception:
            return None
