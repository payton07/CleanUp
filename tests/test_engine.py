"""End-to-end engine tests: sorting, dry-run, events, manifest, undo."""

from __future__ import annotations

from pathlib import Path

from cleanup.core.collect import collect_files
from cleanup.core.conflict import ConflictStrategy
from cleanup.core.config import Ruleset
from cleanup.core.engine import Interaction, UnknownDecision, sort_files
from cleanup.core.events import FilePlanned, SortFinished
from cleanup.core.history import HistoryStore


def _sort(sample_dir: Path, **kwargs):
    ruleset = Ruleset()
    files = collect_files(sample_dir, ruleset)
    return sort_files(sample_dir, files, ruleset, **kwargs), ruleset


def test_sort_moves_files_into_categories(sample_dir: Path):
    manifest, _ = _sort(sample_dir)
    assert (sample_dir / "IMAGES" / "photo.jpg").exists()
    assert (sample_dir / "SCRIPTS" / "script.py").exists()
    assert (sample_dir / "DOCS" / "report.pdf").exists()
    assert (sample_dir / "OTHERS" / "weird.xyzzy").exists()
    assert not (sample_dir / "photo.jpg").exists()
    assert len(manifest) == 9


def test_dry_run_moves_nothing(sample_dir: Path):
    manifest, _ = _sort(sample_dir, dry_run=True)
    assert manifest == []
    assert (sample_dir / "photo.jpg").exists()
    assert not (sample_dir / "IMAGES").exists()


def test_events_emitted(sample_dir: Path):
    events = []
    _sort(sample_dir, on_event=events.append)
    planned = [e for e in events if isinstance(e, FilePlanned)]
    finished = [e for e in events if isinstance(e, SortFinished)]
    assert len(planned) == 9
    assert finished and finished[0].moved == 9


def test_history_record_undo_redo(sample_dir: Path):
    manifest, ruleset = _sort(sample_dir)
    store = HistoryStore(sample_dir)
    store.record("sort", manifest)
    assert store.can_undo

    result = store.undo(ruleset.managed_dirs)
    assert result.ok
    assert result.restored == 9
    # files back in place, category folders pruned
    assert (sample_dir / "photo.jpg").exists()
    assert not (sample_dir / "IMAGES").exists()

    # redo re-applies
    store2 = HistoryStore(sample_dir)
    assert store2.can_redo
    redo = store2.redo()
    assert redo.ok
    assert (sample_dir / "IMAGES" / "photo.jpg").exists()
    assert not (sample_dir / "photo.jpg").exists()


def test_undo_without_history(tmp_path: Path):
    result = HistoryStore(tmp_path).undo(Ruleset().managed_dirs)
    assert not result.ok
    assert result.reason == "nothing-to-undo"


def test_multi_level_undo(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    ruleset = Ruleset()
    store = HistoryStore(tmp_path)

    # run 1
    files = collect_files(tmp_path, ruleset)
    store.record("run1", sort_files(tmp_path, files, ruleset))
    # run 2
    (tmp_path / "b.txt").write_text("y")
    files = collect_files(tmp_path, ruleset)
    store.record("run2", sort_files(tmp_path, files, ruleset))

    # undo twice, in reverse order
    HistoryStore(tmp_path).undo(ruleset.managed_dirs)   # undoes run2
    assert (tmp_path / "b.txt").exists()
    HistoryStore(tmp_path).undo(ruleset.managed_dirs)   # undoes run1
    assert (tmp_path / "a.py").exists()


def test_smart_tags_nest_under_theme(tmp_path: Path):
    (tmp_path / "uml_diagram.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    )
    ruleset = Ruleset()
    ruleset.themes = {"Architecture": ["uml"]}
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset, smart=True)
    assert (tmp_path / "Architecture" / "IMAGES" / "uml_diagram.png").exists()


def test_interaction_skip_unknown(sample_dir: Path):
    class SkipUnknown(Interaction):
        def handle_unknown(self, file: Path) -> UnknownDecision:
            return UnknownDecision(action="skip")

    ruleset = Ruleset()
    files = collect_files(sample_dir, ruleset)
    manifest = sort_files(sample_dir, files, ruleset, interaction=SkipUnknown())
    assert not (sample_dir / "OTHERS").exists()
    assert all(r.category != "OTHERS" for r in manifest)


def test_conflict_skip_strategy(tmp_path: Path):
    (tmp_path / "a.txt").write_text("original")
    (tmp_path / "TEXTS").mkdir()
    (tmp_path / "TEXTS" / "a.txt").write_text("existing")

    ruleset = Ruleset()
    files = collect_files(tmp_path, ruleset)
    manifest = sort_files(tmp_path, files, ruleset, conflict_strategy=ConflictStrategy.SKIP)
    # the incoming a.txt is skipped, existing one untouched
    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "TEXTS" / "a.txt").read_text() == "existing"
    assert manifest == []


def test_move_error_is_isolated(tmp_path: Path, monkeypatch):
    """A single failing move must not abort the run; good files stay in the manifest."""
    import cleanup.core.engine as eng
    (tmp_path / "good.py").write_text("x")
    (tmp_path / "bad.txt").write_text("y")

    real_move = eng.shutil.move
    def fake_move(src, dst):
        if str(src).endswith("bad.txt"):
            raise OSError("boom")
        return real_move(src, dst)
    monkeypatch.setattr(eng.shutil, "move", fake_move)

    ruleset = Ruleset()
    files = collect_files(tmp_path, ruleset)
    manifest = sort_files(tmp_path, files, ruleset)

    assert (tmp_path / "SCRIPTS" / "good.py").exists()
    assert (tmp_path / "bad.txt").exists()          # not moved, not lost
    assert [r.category for r in manifest] == ["SCRIPTS"]


def test_safe_category_neutralizes_traversal():
    from cleanup.core.engine import _safe_category
    assert _safe_category("../evil") == "evil"
    assert _safe_category("/etc/passwd") == "etc/passwd"
    assert _safe_category("IMAGES/SCREENSHOTS") == "IMAGES/SCREENSHOTS"
    assert _safe_category("..") == "OTHERS"
    assert _safe_category("") == "OTHERS"


def test_rule_category_traversal_stays_inside(tmp_path: Path):
    from cleanup.core.rules import parse_rules
    (tmp_path / "x.txt").write_text("hi")
    ruleset = Ruleset(rules=parse_rules([{"name": "*.txt", "category": "../evil"}]))
    files = collect_files(tmp_path, ruleset)
    sort_files(tmp_path, files, ruleset)
    assert (tmp_path / "EVIL" / "x.txt").exists()
    assert not (tmp_path.parent / "evil").exists()


def test_dry_run_previews_distinct_dests(tmp_path: Path):
    from cleanup.core.events import FilePlanned
    (tmp_path / "sub1").mkdir(); (tmp_path / "sub2").mkdir()
    (tmp_path / "sub1" / "a.txt").write_text("1")
    (tmp_path / "sub2" / "a.txt").write_text("2")
    ruleset = Ruleset()
    files = collect_files(tmp_path, ruleset, recursive=True)
    dests: list[str] = []
    def cap(ev):
        if isinstance(ev, FilePlanned):
            dests.append(str(ev.dest))
    sort_files(tmp_path, files, ruleset, dry_run=True, on_event=cap)
    assert len(dests) == 2 and len(set(dests)) == 2   # a.txt and a_1.txt
