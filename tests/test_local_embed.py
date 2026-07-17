"""Local embedding backend + backend resolver tests.

These run offline and never download a model: the real fastembed path is only
smoke-checked when the library is installed, and the resolver logic is tested
with monkeypatched availability.
"""

from __future__ import annotations

import cleanup.ai.backends as backends
from cleanup.ai.local_embed import LocalEmbedder
from cleanup.ai import backends as backends_mod


def test_local_embedder_graceful_without_fastembed(monkeypatch):
    """If fastembed can't load, embed() returns None instead of raising."""
    emb = LocalEmbedder()
    monkeypatch.setattr(emb, "_ensure_model", lambda: False)
    assert emb.embed("hello") is None


def test_local_embedder_available_is_bool():
    assert isinstance(LocalEmbedder.available(), bool)


def test_resolve_prefers_local_in_auto(monkeypatch):
    monkeypatch.setattr(backends.LocalEmbedder, "available", staticmethod(lambda: True))
    emb, threshold, label = backends.resolve_embedder("auto")
    assert isinstance(emb, LocalEmbedder)
    assert label.startswith("local")
    assert threshold == backends.LOCAL_THRESHOLD


def test_resolve_local_unavailable_message(monkeypatch):
    monkeypatch.setattr(backends.LocalEmbedder, "available", staticmethod(lambda: False))
    emb, threshold, reason = backends.resolve_embedder("local")
    assert emb is None
    assert "pip install" in reason


def test_resolve_auto_falls_back_to_ollama(monkeypatch):
    monkeypatch.setattr(backends.LocalEmbedder, "available", staticmethod(lambda: False))

    class FakeOllama:
        def __init__(self, model=None):
            self.embed_model = None
        def available(self):
            return True
        def pick_embed_model(self):
            self.embed_model = "nomic-embed-text:latest"
            return self.embed_model

    monkeypatch.setattr(backends, "OllamaClient", FakeOllama)
    emb, threshold, label = backends.resolve_embedder("auto")
    assert isinstance(emb, FakeOllama)
    assert label.startswith("ollama")
    assert threshold == backends.OLLAMA_THRESHOLD


def test_resolve_none_available(monkeypatch):
    monkeypatch.setattr(backends.LocalEmbedder, "available", staticmethod(lambda: False))

    class DownOllama:
        def __init__(self, model=None):
            pass
        def available(self):
            return False
        def pick_embed_model(self):
            return None

    monkeypatch.setattr(backends, "OllamaClient", DownOllama)
    emb, threshold, reason = backends.resolve_embedder("auto")
    assert emb is None and threshold is None
    assert "no embedding backend" in reason


def test_env_threshold_override(monkeypatch):
    monkeypatch.setattr(backends.LocalEmbedder, "available", staticmethod(lambda: True))
    monkeypatch.setattr(backends_mod, "_ENV_THRESHOLD", "0.7")
    _, threshold, _ = backends.resolve_embedder("local")
    assert threshold == 0.7
