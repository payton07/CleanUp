"""Periodic scheduling — run a CleanUp sort on a timer.

Complements watch mode (event-based) with time-based runs: "sort my Downloads
every day". Generates a **launchd** agent on macOS and a **cron** line on Linux.

The plist/cron *generators* are pure functions (easy to test); installation
writes the file and activates it. A ``$CLEANUP_LAUNCHAGENTS`` override lets tests
install into a temp dir without touching the real system.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CADENCES = ("hourly", "daily", "weekly")
_DAILY_HOUR = 12  # noon


def schedule_label(directory: Path) -> str:
    """Stable launchd label / cron tag for a directory."""
    digest = hashlib.blake2b(str(directory).encode(), digest_size=4).hexdigest()
    return f"com.cleanup.{digest}"


def launchagents_dir() -> Path:
    override = os.environ.get("CLEANUP_LAUNCHAGENTS")
    return Path(override) if override else Path.home() / "Library" / "LaunchAgents"


def cleanup_command() -> list[str]:
    """Best invocation of CleanUp for a scheduled job."""
    if getattr(sys, "frozen", False):          # PyInstaller binary
        return [sys.executable]
    found = shutil.which("cleanup")
    if found:
        return [found]
    return [sys.executable, "-m", "cleanup"]


def _calendar_interval(cadence: str) -> dict | int:
    if cadence == "hourly":
        return 3600                             # StartInterval (seconds)
    if cadence == "weekly":
        return {"Weekday": 0, "Hour": _DAILY_HOUR, "Minute": 0}
    return {"Hour": _DAILY_HOUR, "Minute": 0}   # daily


def build_launchd_plist(label: str, program_args: list[str], cadence: str) -> bytes:
    plist: dict = {
        "Label": label,
        "ProgramArguments": program_args,
        "RunAtLoad": False,
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / f"{label}.log"),
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / f"{label}.log"),
    }
    interval = _calendar_interval(cadence)
    if isinstance(interval, int):
        plist["StartInterval"] = interval
    else:
        plist["StartCalendarInterval"] = interval
    return plistlib.dumps(plist)


def build_cron_line(command: list[str], cadence: str, tag: str) -> str:
    schedule = {
        "hourly": "0 * * * *",
        "daily": f"0 {_DAILY_HOUR} * * *",
        "weekly": f"0 {_DAILY_HOUR} * * 0",
    }[cadence]
    cmd = " ".join(command)
    return f"{schedule} {cmd}  # {tag}"


@dataclass
class ScheduleResult:
    kind: str          # "launchd" | "cron"
    path: str
    label: str
    activated: bool


def program_args(directory: Path, extra: list[str]) -> list[str]:
    return [*cleanup_command(), str(directory), *extra]


# ─── INSTALL / UNINSTALL ────────────────────────────────────────────────────

def install(directory: Path, extra: list[str], cadence: str, *, activate: bool = True) -> ScheduleResult:
    if sys.platform == "darwin":
        return _install_launchd(directory, extra, cadence, activate=activate)
    return _install_cron(directory, extra, cadence)


def uninstall(directory: Path, *, activate: bool = True) -> bool:
    if sys.platform == "darwin":
        return _uninstall_launchd(directory, activate=activate)
    return _uninstall_cron(directory)


def _install_launchd(directory: Path, extra: list[str], cadence: str, *, activate: bool) -> ScheduleResult:
    label = schedule_label(directory)
    args = program_args(directory, extra)
    plist = build_launchd_plist(label, args, cadence)
    agents = launchagents_dir()
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{label}.plist"
    path.write_bytes(plist)

    activated = False
    if activate:
        try:
            subprocess.run(["launchctl", "unload", str(path)],
                           capture_output=True, check=False)
            subprocess.run(["launchctl", "load", "-w", str(path)],
                           capture_output=True, check=True)
            activated = True
        except (OSError, subprocess.SubprocessError):
            activated = False
    return ScheduleResult("launchd", str(path), label, activated)


def _uninstall_launchd(directory: Path, *, activate: bool) -> bool:
    label = schedule_label(directory)
    path = launchagents_dir() / f"{label}.plist"
    if not path.exists():
        return False
    if activate:
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
    path.unlink()
    return True


def _crontab_read() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def _crontab_write(content: str) -> None:
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def _install_cron(directory: Path, extra: list[str], cadence: str) -> ScheduleResult:
    tag = schedule_label(directory)
    line = build_cron_line(program_args(directory, extra), cadence, tag)
    existing = [ln for ln in _crontab_read().splitlines() if tag not in ln]
    existing.append(line)
    _crontab_write("\n".join(existing) + "\n")
    return ScheduleResult("cron", "crontab", tag, True)


def _uninstall_cron(directory: Path) -> bool:
    tag = schedule_label(directory)
    lines = _crontab_read().splitlines()
    kept = [ln for ln in lines if tag not in ln]
    if len(kept) == len(lines):
        return False
    _crontab_write("\n".join(kept) + ("\n" if kept else ""))
    return True
