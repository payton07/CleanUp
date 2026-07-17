"""Embedding-backend resolution shared by the CLI and web.

Chooses where the ``--ai`` (embedding) mode runs:

- ``local``  — in-process via fastembed (no server; see :mod:`local_embed`)
- ``ollama`` — the local Ollama server
- ``auto``   — prefer local if installed, else Ollama

Each backend carries its own calibrated cosine threshold (the models sit on
different similarity scales); ``CLEANUP_AI_THRESHOLD`` overrides either.
"""

from __future__ import annotations

import os

from .local_embed import DEFAULT_THRESHOLD as LOCAL_THRESHOLD
from .local_embed import LocalEmbedder
from .ollama import OllamaClient

# Base threshold for an Ollama embedding model (nomic-embed-text), calibrated in
# scripts/calibrate_threshold.py.
OLLAMA_THRESHOLD = 0.56

_ENV_THRESHOLD = os.environ.get("CLEANUP_AI_THRESHOLD")


def _threshold(default: float) -> float:
    if _ENV_THRESHOLD:
        try:
            return float(_ENV_THRESHOLD)
        except ValueError:
            pass
    return default


def resolve_embedder(backend: str = "auto", *, ollama_model: str | None = None):
    """Pick an embedding backend.

    Returns ``(embedder, threshold, label)`` on success, or
    ``(None, None, reason)`` when the requested backend is unavailable.
    """
    backend = (backend or "auto").lower()

    def try_local():
        if LocalEmbedder.available():
            emb = LocalEmbedder()
            return emb, _threshold(LOCAL_THRESHOLD), f"local ({emb.model_name})"
        return None

    def try_ollama():
        client = OllamaClient(model=ollama_model)
        if client.available() and client.pick_embed_model():
            return client, _threshold(OLLAMA_THRESHOLD), f"ollama ({client.embed_model})"
        return None

    if backend == "local":
        return try_local() or (
            None, None,
            "local backend unavailable — `pip install cleanup-cli[embed]`",
        )
    if backend == "ollama":
        return try_ollama() or (
            None, None,
            "ollama backend unavailable — run `ollama serve` and pull an embedding model",
        )
    # auto: prefer in-process local, fall back to Ollama
    return try_local() or try_ollama() or (
        None, None,
        "no embedding backend — `pip install cleanup-cli[embed]` or run Ollama",
    )
