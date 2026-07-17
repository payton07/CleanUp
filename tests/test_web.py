"""Web API tests via FastAPI's TestClient (REST + WebSocket)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cleanup.web.server import app  # noqa: E402

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "CleanUp" in r.text


def test_browse_lists_dirs(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    r = client.get("/api/browse", params={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert "sub" in data["dirs"]
    assert data["path"] == str(tmp_path)


def test_scan_reports_plan(sample_dir: Path):
    r = client.post("/api/scan", json={"path": str(sample_dir)})
    data = r.json()
    assert data["count"] == 9
    assert data["by_category"]["IMAGES"] == 3
    # nothing moved by a scan
    assert (sample_dir / "photo.jpg").exists()


def test_scan_invalid_dir():
    r = client.post("/api/scan", json={"path": "/no/such/dir/xyz"})
    assert r.status_code == 400
    assert "error" in r.json()


def test_ws_sort_streams_and_moves(sample_dir: Path):
    with client.websocket_connect("/ws/sort") as ws:
        ws.send_json({"path": str(sample_dir)})
        types = []
        summary = None
        while True:
            msg = ws.receive_json()
            types.append(msg["type"])
            if msg["type"] == "summary":
                summary = msg
                break
        assert "file_planned" in types
        assert summary["moved"] == 9
    assert (sample_dir / "IMAGES" / "photo.jpg").exists()


def test_history_undo_redo_cycle(sample_dir: Path):
    # sort via websocket first
    with client.websocket_connect("/ws/sort") as ws:
        ws.send_json({"path": str(sample_dir)})
        while ws.receive_json()["type"] != "summary":
            pass

    h = client.get("/api/history", params={"path": str(sample_dir)}).json()
    assert h["can_undo"] and h["sessions"]

    u = client.post("/api/undo", json={"path": str(sample_dir)}).json()
    assert u["ok"] and u["restored"] == 9
    assert (sample_dir / "photo.jpg").exists()

    r = client.post("/api/redo", json={"path": str(sample_dir)}).json()
    assert r["ok"]
    assert (sample_dir / "IMAGES" / "photo.jpg").exists()


def test_dedupe_endpoint(tmp_path: Path):
    (tmp_path / "a.txt").write_text("dup")
    (tmp_path / "b.txt").write_text("dup")
    r = client.post("/api/dedupe", json={"path": str(tmp_path), "recursive": False}).json()
    assert len(r["groups"]) == 1
    assert r["groups"][0]["paths"][0].endswith("a.txt")
