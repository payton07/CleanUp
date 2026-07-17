"""Adaptive AI: decision memory + AdaptiveClassifier (offline)."""

from __future__ import annotations

from pathlib import Path

from cleanup.ai.adaptive import AdaptiveClassifier
from cleanup.ai.memory import DecisionStore


class FakeEmbed:
    """Deterministic bag-of-words embedder over a tiny vocabulary."""
    VOCAB = ("invoice", "payment", "recipe", "ingredients", "log", "error")

    def embed(self, text, model=None):
        t = text.lower()
        return [float(t.count(w)) for w in self.VOCAB]


class FakeBase:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def classify(self, path, current_category):
        self.calls += 1
        return self.result


# ── DecisionStore ──

def test_store_add_nearest_roundtrip(tmp_path: Path):
    store = DecisionStore(path=tmp_path / "d.json")
    assert len(store) == 0
    assert store.nearest([1.0, 0.0]) is None
    store.add([1.0, 0.0], "INVOICES")
    cat, score = store.nearest([1.0, 0.0])
    assert cat == "INVOICES"
    assert score > 0.99


def test_store_persists(tmp_path: Path):
    p = tmp_path / "d.json"
    DecisionStore(path=p).add([0.0, 1.0], "RECIPES")
    reloaded = DecisionStore(path=p)
    assert len(reloaded) == 1
    assert reloaded.nearest([0.0, 1.0])[0] == "RECIPES"


def test_store_corrupt_file_is_ignored(tmp_path: Path):
    p = tmp_path / "d.json"
    p.write_text("{ not json")
    assert len(DecisionStore(path=p)) == 0


# ── AdaptiveClassifier ──

def _adaptive(tmp_path, base_result="TEXTS"):
    store = DecisionStore(path=tmp_path / "decisions.json")
    return AdaptiveClassifier(FakeEmbed(), FakeBase(base_result), store), store


def test_empty_memory_falls_back_to_base(tmp_path: Path):
    f = tmp_path / "a.txt"; f.write_text("invoice payment")
    ai, _ = _adaptive(tmp_path, base_result="DOCS")
    assert ai.classify(f, "TEXTS") == "DOCS"
    assert ai._base.calls == 1


def test_learns_from_correction(tmp_path: Path):
    a = tmp_path / "a.txt"; a.write_text("invoice payment")
    b = tmp_path / "b.txt"; b.write_text("invoice payment")   # same content
    ai, store = _adaptive(tmp_path, base_result="TEXTS")

    assert ai.record(a, "MY_INVOICES") is True
    assert len(store) == 1
    # a near-identical file now inherits the corrected category, not the base one
    assert ai.classify(b, "TEXTS") == "MY_INVOICES"
    assert ai._base.calls == 0


def test_dissimilar_file_uses_base(tmp_path: Path):
    a = tmp_path / "a.txt"; a.write_text("invoice payment")
    other = tmp_path / "c.txt"; other.write_text("recipe ingredients")
    ai, _ = _adaptive(tmp_path, base_result="TEXTS")
    ai.record(a, "MY_INVOICES")
    # cosine with the invoice memory is ~0 → below threshold → base wins
    assert ai.classify(other, "TEXTS") == "TEXTS"


def test_threshold_respected(tmp_path: Path):
    a = tmp_path / "a.txt"; a.write_text("invoice payment")
    b = tmp_path / "b.txt"; b.write_text("invoice payment")
    store = DecisionStore(path=tmp_path / "d.json")
    ai = AdaptiveClassifier(FakeEmbed(), FakeBase("TEXTS"), store, adapt_threshold=1.01)
    ai.record(a, "X")
    # threshold above 1.0 can never match → always base
    assert ai.classify(b, "TEXTS") == "TEXTS"
