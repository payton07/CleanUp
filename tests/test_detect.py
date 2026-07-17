"""Detection tests: content sniffing, extension refinement, fallback."""

from __future__ import annotations

from pathlib import Path

from cleanup.core import detect
from cleanup.core.config import Ruleset
from cleanup.core.detect import detect_category, detect_theme


def test_binary_types_by_content(sample_dir: Path):
    rs = Ruleset()
    assert detect_category(sample_dir / "photo.jpg", rs) == "IMAGES"
    assert detect_category(sample_dir / "icon.png", rs) == "IMAGES"
    assert detect_category(sample_dir / "anim.gif", rs) == "IMAGES"
    assert detect_category(sample_dir / "report.pdf", rs) == "DOCS"
    assert detect_category(sample_dir / "bundle.zip", rs) == "ARCHIVES"


def test_text_split_scripts_vs_texts(sample_dir: Path):
    rs = Ruleset()
    # libmagic reports both as text/plain; extension must break the tie.
    assert detect_category(sample_dir / "script.py", rs) == "SCRIPTS"
    assert detect_category(sample_dir / "notes.txt", rs) == "TEXTS"
    assert detect_category(sample_dir / "data.csv", rs) == "TEXTS"


def test_unknown_is_others(sample_dir: Path):
    rs = Ruleset()
    assert detect_category(sample_dir / "weird.xyzzy", rs) == "OTHERS"


def test_content_beats_lying_extension(tmp_path: Path):
    """A JPEG named .txt must still be classified as an image when content
    detection is available."""
    liar = tmp_path / "actually_an_image.txt"
    liar.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32 + b"\xff\xd9"
    )
    result = detect_category(liar, Ruleset())
    if detect.CONTENT_DETECTION:
        assert result == "IMAGES"
    else:
        # Degraded mode: extension wins, so it reads as TEXTS.
        assert result == "TEXTS"


def test_extension_fallback_when_no_content_detection(tmp_path: Path, monkeypatch):
    """With sniffing disabled, extension fallback still classifies files."""
    monkeypatch.setattr(detect, "_MAGIC", None)
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert detect_category(f, Ruleset()) == "VIDEOS"


def test_theme_detection_from_name_and_path(tmp_path: Path):
    rs = Ruleset()
    rs.themes = {"Architecture": ["uml", "arch"]}
    assert detect_theme(tmp_path / "my_uml_diagram.png", rs) == "Architecture"
    assert detect_theme(tmp_path / "holiday.png", rs) is None


def test_theme_none_when_no_themes(tmp_path: Path):
    assert detect_theme(tmp_path / "uml.png", Ruleset()) is None
