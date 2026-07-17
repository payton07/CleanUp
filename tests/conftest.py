"""Shared fixtures: real file bytes so content detection is exercised."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

# Minimal but valid magic-byte payloads.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32 + b"\xff\xd9"
GIF_BYTES = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00;"
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 26 + b"PK\x05\x06" + b"\x00" * 18


def _png_bytes() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    chunk += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    return sig + chunk + iend


PNG_BYTES = _png_bytes()


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """A directory populated with a spread of real file types."""
    (tmp_path / "photo.jpg").write_bytes(JPEG_BYTES)
    (tmp_path / "icon.png").write_bytes(PNG_BYTES)
    (tmp_path / "anim.gif").write_bytes(GIF_BYTES)
    (tmp_path / "report.pdf").write_bytes(PDF_BYTES)
    (tmp_path / "bundle.zip").write_bytes(ZIP_BYTES)
    (tmp_path / "script.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("just some notes\n", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    (tmp_path / "weird.xyzzy").write_bytes(b"\x00\x01mystery\x02\x03")
    return tmp_path
