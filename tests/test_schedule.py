"""Scheduling: plist/cron generation and install-to-temp (no launchctl/crontab)."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from cleanup.core import schedule


def test_label_is_stable_and_dir_specific():
    a = schedule.schedule_label(Path("/tmp/one"))
    b = schedule.schedule_label(Path("/tmp/one"))
    c = schedule.schedule_label(Path("/tmp/two"))
    assert a == b and a != c
    assert a.startswith("com.cleanup.")


def test_build_launchd_plist_daily():
    data = schedule.build_launchd_plist("com.cleanup.x", ["cleanup", "/d", "--smart"], "daily")
    parsed = plistlib.loads(data)
    assert parsed["Label"] == "com.cleanup.x"
    assert parsed["ProgramArguments"] == ["cleanup", "/d", "--smart"]
    assert parsed["StartCalendarInterval"] == {"Hour": 12, "Minute": 0}


def test_build_launchd_plist_hourly_uses_interval():
    parsed = plistlib.loads(schedule.build_launchd_plist("l", ["cleanup", "/d"], "hourly"))
    assert parsed["StartInterval"] == 3600
    assert "StartCalendarInterval" not in parsed


def test_build_launchd_plist_weekly():
    parsed = plistlib.loads(schedule.build_launchd_plist("l", ["cleanup", "/d"], "weekly"))
    assert parsed["StartCalendarInterval"]["Weekday"] == 0


def test_build_cron_line():
    line = schedule.build_cron_line(["cleanup", "/d", "--smart"], "daily", "com.cleanup.x")
    assert line.startswith("0 12 * * *")
    assert "cleanup /d --smart" in line
    assert line.endswith("# com.cleanup.x")


def test_install_and_uninstall_launchd_in_tempdir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLEANUP_LAUNCHAGENTS", str(tmp_path / "agents"))
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    target = tmp_path / "Downloads"; target.mkdir()

    result = schedule.install(target, ["--smart"], "daily", activate=False)
    assert result.kind == "launchd"
    plist_path = Path(result.path)
    assert plist_path.exists()
    parsed = plistlib.loads(plist_path.read_bytes())
    assert "--smart" in parsed["ProgramArguments"]
    assert parsed["StartCalendarInterval"] == {"Hour": 12, "Minute": 0}

    # uninstall removes the plist
    assert schedule.uninstall(target, activate=False) is True
    assert not plist_path.exists()
    # uninstalling again is a no-op
    assert schedule.uninstall(target, activate=False) is False


def test_program_args_includes_directory_and_extra(tmp_path: Path):
    args = schedule.program_args(tmp_path, ["--recursive"])
    assert str(tmp_path) in args
    assert args[-1] == "--recursive"
