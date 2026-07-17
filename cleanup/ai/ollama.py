"""Minimal Ollama HTTP client (stdlib only).

Talks to a locally running Ollama server (default ``http://localhost:11434``).
Kept dependency-free on purpose so the AI feature never forces extra installs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL_ENV = os.environ.get("CLEANUP_OLLAMA_MODEL")


class OllamaClient:
    def __init__(self, host: str = DEFAULT_HOST, model: str | None = None, timeout: float = 30.0):
        self.host = host.rstrip("/")
        self.model = model or DEFAULT_MODEL_ENV
        self.embed_model: str | None = None
        self.timeout = timeout

    # ── connectivity ──
    def _get(self, path: str, timeout: float | None = None) -> dict | None:
        try:
            req = urllib.request.Request(self.host + path, method="GET")
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None

    def available(self) -> bool:
        """True if the Ollama server responds."""
        return self._get("/api/tags", timeout=2.0) is not None

    def list_models(self) -> list[str]:
        data = self._get("/api/tags", timeout=3.0) or {}
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def resolve_model(self) -> str | None:
        """Pick the configured model, or the first available text model."""
        models = self.list_models()
        if not models:
            return None
        if self.model:
            # Accept an exact match or a tag-less alias ("mistral" → "mistral:latest").
            for m in models:
                if m == self.model or m.split(":")[0] == self.model:
                    self.model = m
                    return m
        # Prefer plain text models over multimodal/vision ones for classification,
        # and avoid embedding-only models for generation.
        text_models = [m for m in models
                       if "vision" not in m.lower() and "embed" not in m.lower()]
        chosen = (text_models or models)[0]
        self.model = chosen
        return chosen

    def pick_embed_model(self) -> str | None:
        """Find an installed embedding model (name contains 'embed')."""
        for m in self.list_models():
            if "embed" in m.lower():
                self.embed_model = m
                return m
        return None

    # ── inference ──
    def generate(self, prompt: str, system: str | None = None) -> str | None:
        """Single-shot completion via ``/api/generate`` (non-streaming)."""
        model = self.model or self.resolve_model()
        if not model:
            return None
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            req = urllib.request.Request(
                self.host + "/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None

    def embed(self, text: str, model: str | None = None) -> list[float] | None:
        """Return an embedding vector for ``text`` via ``/api/embeddings``."""
        m = model or self.embed_model or self.pick_embed_model()
        if not m:
            return None
        payload = {"model": m, "prompt": text}
        try:
            req = urllib.request.Request(
                self.host + "/api/embeddings",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                vec = json.loads(resp.read().decode("utf-8")).get("embedding")
            return vec or None
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return None
