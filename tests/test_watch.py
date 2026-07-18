"""Watch-mode tests. tick() is a pure step, so no threads or sleeps needed."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.config import Ruleset
from cleanup.core.history import HistoryStore
from cleanup.core.watch import Watcher


def _watcher(directory: Path, **kw) -> Watcher:
    return Watcher(directory, Ruleset(), poll_interval=0.01, **kw)


def test_stable_file_sorted_after_two_ticks(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello")
    w = _watcher(tmp_path)
    assert w.tick() == []                       # first sighting → not yet stable
    manifest = w.tick()                          # unchanged size → stable → sorted
    assert len(manifest) == 1
    assert (tmp_path / "TEXTS" / "a.txt").exists()


def test_growing_file_not_sorted(tmp_path: Path):
    f = tmp_path / "download.txt"
    f.write_text("1")
    w = _watcher(tmp_path)
    w.tick()                                     # size recorded
    f.write_text("1234567")                      # still being written
    assert w.tick() == []                        # size changed → debounced
    assert f.exists()                            # not moved


def test_managed_dirs_not_reprocessed(tmp_path: Path):
    (tmp_path / "note.txt").write_text("hi")
    w = _watcher(tmp_path)
    w.tick(); w.tick()                           # sorted into TEXTS/
    assert (tmp_path / "TEXTS" / "note.txt").exists()
    assert w.tick() == []                        # nothing new to do
    assert w.tick() == []


def test_history_recorded_and_undoable(tmp_path: Path):
    (tmp_path / "script.py").write_text("print(1)")
    w = _watcher(tmp_path)
    w.tick(); w.tick()
    assert HistoryStore(tmp_path).can_undo


def test_on_sorted_callback_fires_once(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hi")
    seen: list[int] = []
    w = _watcher(tmp_path, on_sorted=lambda m: seen.append(len(m)))
    w.tick(); w.tick()
    assert seen == [1]


def test_multiple_files_batched(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.py").write_text("y")
    w = _watcher(tmp_path)
    w.tick()
    manifest = w.tick()
    assert len(manifest) == 2
    assert (tmp_path / "TEXTS" / "a.txt").exists()
    assert (tmp_path / "SCRIPTS" / "b.py").exists()


def test_run_survives_tick_error(tmp_path: Path):
    """A raising tick() must not kill the watch loop; on_error fires."""
    w = Watcher(tmp_path, Ruleset(), poll_interval=0.01)
    errors: list[Exception] = []
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] >= 2:
            w.stop()
        raise RuntimeError("boom")

    w.tick = boom
    w.on_error = errors.append
    w.run()   # must return, not hang or propagate
    assert len(errors) >= 1
