"""AI classification tests — offline, using fake generators/embedders (no Ollama)."""

from __future__ import annotations

from pathlib import Path

from cleanup.ai.classify import (
    AiInteraction,
    CreativeClassifier,
    EmbeddingClassifier,
    classify_file,
    read_snippet,
    sanitize_category,
)
from cleanup.ai.ollama import OllamaClient
from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset
from cleanup.core.engine import Interaction, sort_files


class FakeGen:
    """Stand-in generative model that returns a scripted reply and counts calls."""
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def generate(self, prompt, system=None):
        self.calls += 1
        return self.reply


class FakeEmbed:
    """Deterministic bag-of-words embedder over a tiny vocabulary."""
    VOCAB = ("invoice", "payment", "recipe", "ingredients", "log", "error")

    def __init__(self):
        self.calls = 0

    def embed(self, text, model=None):
        self.calls += 1
        t = text.lower()
        return [float(t.count(w)) for w in self.VOCAB]


class FakeClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def classify(self, path, current_category):
        self.calls += 1
        return self.result


# ── sanitize_category ──

def test_sanitize_uppercases_and_cleans():
    assert sanitize_category("invoices") == "INVOICES"
    assert sanitize_category("Bank Statements") == "BANK_STATEMENTS"
    assert sanitize_category('"FONTS".') == "FONTS"
    assert sanitize_category("e-books") == "E_BOOKS"


def test_sanitize_multiline_takes_first():
    assert sanitize_category("LOGS\nsome explanation") == "LOGS"


def test_sanitize_empty_or_none():
    assert sanitize_category(None) is None
    assert sanitize_category("   ") is None
    assert sanitize_category("!!!") is None


# ── read_snippet ──

def test_read_snippet_text(tmp_path: Path):
    f = tmp_path / "a.txt"; f.write_text("hello world")
    assert "hello world" in read_snippet(f)


def test_read_snippet_binary(tmp_path: Path):
    f = tmp_path / "a.bin"; f.write_bytes(b"\x00\x01\x02mystery")
    assert read_snippet(f) == "(binary file)"


def test_read_snippet_empty(tmp_path: Path):
    f = tmp_path / "a"; f.write_bytes(b"")
    assert read_snippet(f) == "(empty file)"


# ── CreativeClassifier (generative) ──

def test_classify_file_uses_reply(tmp_path: Path):
    f = tmp_path / "notes.xyz"; f.write_text("meeting notes")
    assert classify_file(FakeGen("NOTES"), f, ["IMAGES"]) == "NOTES"


def test_creative_classifier_caches_by_ext(tmp_path: Path):
    a = tmp_path / "one.foo"; a.write_text("x")
    b = tmp_path / "two.foo"; b.write_text("y")
    gen = FakeGen("DATASETS")
    clf = CreativeClassifier(gen, ["IMAGES"])
    assert clf.classify(a, "TEXTS") == "DATASETS"
    assert clf.classify(b, "OTHERS") == "DATASETS"
    assert gen.calls == 1  # same extension → single call


# ── EmbeddingClassifier (zero-shot) ──

_CATS = {"INVOICES": "invoice payment", "RECIPES": "recipe ingredients", "LOGS": "log error"}


def test_embedding_classifier_picks_nearest(tmp_path: Path):
    f = tmp_path / "doc.txt"; f.write_text("invoice payment due next week")
    clf = EmbeddingClassifier(FakeEmbed(), _CATS, threshold=0.3)
    assert clf.classify(f, "TEXTS") == "INVOICES"


def test_embedding_classifier_content_over_name(tmp_path: Path):
    # Two .txt files with different content must classify differently.
    inv = tmp_path / "a.txt"; inv.write_text("invoice payment")
    rec = tmp_path / "b.txt"; rec.write_text("recipe ingredients bake")
    clf = EmbeddingClassifier(FakeEmbed(), _CATS, threshold=0.3)
    assert clf.classify(inv, "TEXTS") == "INVOICES"
    assert clf.classify(rec, "TEXTS") == "RECIPES"


def test_embedding_classifier_below_threshold_returns_none(tmp_path: Path):
    f = tmp_path / "x.txt"; f.write_text("nothing relevant here")
    clf = EmbeddingClassifier(FakeEmbed(), _CATS, threshold=0.3)
    assert clf.classify(f, "TEXTS") is None


def test_embedding_labels_computed_once(tmp_path: Path):
    client = FakeEmbed()
    clf = EmbeddingClassifier(client, _CATS, threshold=0.3)
    a = tmp_path / "a.txt"; a.write_text("invoice payment")
    b = tmp_path / "b.txt"; b.write_text("invoice payment")
    clf.classify(a, "TEXTS")
    clf.classify(b, "TEXTS")
    # 3 label embeds (once) + 1 per file = 5, i.e. labels not recomputed.
    assert client.calls == 3 + 2


# ── AiInteraction (classifier-agnostic) ──

def test_ai_refine_uses_classifier(tmp_path: Path):
    clf = FakeClassifier("DATASETS")
    ai = AiInteraction(clf)
    f = tmp_path / "a.txt"
    assert ai.refine_category(f, "TEXTS") == "DATASETS"
    assert str(f) in ai.suggested


def test_ai_leaves_concrete_categories_untouched(tmp_path: Path):
    clf = FakeClassifier("SHOULD_NOT_BE_USED")
    ai = AiInteraction(clf)
    assert ai.refine_category(tmp_path / "pic.jpg", "IMAGES") == "IMAGES"
    assert clf.calls == 0  # concrete category → classifier not consulted


def test_ai_refine_falls_back_when_no_answer(tmp_path: Path):
    ai = AiInteraction(FakeClassifier(None))
    assert ai.refine_category(tmp_path / "weird.zzz", "OTHERS") == "OTHERS"


def test_ai_interaction_passes_through_theme(tmp_path: Path):
    class Base(Interaction):
        def confirm_theme(self, file, theme): return False
    ai = AiInteraction(FakeClassifier("X"), wrap=Base())
    assert ai.confirm_theme(tmp_path / "f", "Theme") is False


def test_sort_with_ai_refines_texts_file(tmp_path: Path):
    (tmp_path / "invoice.txt").write_text("Invoice #123, total $500")
    ruleset = Ruleset()
    ai = AiInteraction(FakeClassifier("INVOICES"))
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset, interaction=ai)
    assert (tmp_path / "INVOICES" / "invoice.txt").exists()
    assert not (tmp_path / "TEXTS").exists()


# ── OllamaClient (offline) ──

def test_client_unavailable_offline():
    client = OllamaClient(host="http://localhost:1", timeout=1.0)
    assert client.available() is False
    assert client.list_models() == []
    assert client.resolve_model() is None
    assert client.pick_embed_model() is None
    assert client.embed("hello") is None
