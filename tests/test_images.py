"""Image sub-sorting tests — offline with a fake CLIP embedder."""

from __future__ import annotations

from pathlib import Path

from cleanup.ai.images import ImageClassifier, ImageEmbedder, ImageInteraction
from cleanup.core.collect import collect_files
from cleanup.core.config import Ruleset
from cleanup.core.engine import Interaction, sort_files

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 40 + b"\xff\xd9"

_CATS = {
    "SCREENSHOTS": "screenshot ui",
    "PHOTOS": "photo picture",
    "DOCUMENTS": "document text",
    "MEMES": "meme funny",
}


class FakeClip:
    """Bag-of-concepts CLIP stand-in: image concept comes from the file name."""
    CONCEPTS = ("screenshot", "photo", "document", "meme")

    def embed_image(self, path):
        name = str(path).lower()
        return [1.0 if c in name else 0.0 for c in self.CONCEPTS]

    def embed_text(self, text):
        t = text.lower()
        return [1.0 if c in t else 0.0 for c in self.CONCEPTS]


def _classifier():
    return ImageClassifier(FakeClip(), _CATS, threshold=0.1)


def test_classify_picks_nearest_subtype():
    clf = _classifier()
    assert clf.classify(Path("my_screenshot_2026.png")) == "SCREENSHOTS"
    assert clf.classify(Path("vacation_photo.jpg")) == "PHOTOS"
    assert clf.classify(Path("scan_document.png")) == "DOCUMENTS"


def test_classify_below_threshold_returns_none():
    clf = ImageClassifier(FakeClip(), _CATS, threshold=0.1)
    assert clf.classify(Path("random_noise.png")) is None  # no concept → score 0


def test_interaction_refines_images_only():
    ii = ImageInteraction(_classifier())
    assert ii.refine_category(Path("app_screenshot.png"), "IMAGES") == "IMAGES/SCREENSHOTS"
    # non-image categories pass straight through
    assert ii.refine_category(Path("notes.txt"), "TEXTS") == "TEXTS"


def test_interaction_delegates_non_images_to_wrap():
    class TextRefiner(Interaction):
        def refine_category(self, file, category):
            return "REFINED" if category == "TEXTS" else category

    ii = ImageInteraction(_classifier(), wrap=TextRefiner())
    assert ii.refine_category(Path("x.txt"), "TEXTS") == "REFINED"
    assert ii.refine_category(Path("s_screenshot.png"), "IMAGES") == "IMAGES/SCREENSHOTS"


def test_low_confidence_image_stays_in_images():
    ii = ImageInteraction(_classifier())
    assert ii.refine_category(Path("mystery.png"), "IMAGES") == "IMAGES"


def test_engine_subsorts_image_into_nested_folder(tmp_path: Path):
    (tmp_path / "beach_photo.jpg").write_bytes(_JPEG)
    ruleset = Ruleset()
    ii = ImageInteraction(_classifier())
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset, interaction=ii)
    assert (tmp_path / "IMAGES" / "PHOTOS" / "beach_photo.jpg").exists()


def test_embedder_available_is_bool():
    assert isinstance(ImageEmbedder.available(), bool)
