"""Install and remove the nightly worklog report schedule."""

from __future__ import annotations

import os
import platform
import plistlib
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import worklog

from .paths import ensure_private_dir, ledger_root


LABEL = "com.worklog.report"
CRONTAB_MARKER = "# worklog-report"
LOG_NAME = "schedule.log"
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class CommandResult(Protocol):
    """The subset of subprocess results needed by schedule operations."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], str | None], CommandResult]


@dataclass(frozen=True)
class ScheduleResult:
    """Description of a schedule operation and its resulting state."""

    action: str
    platform: str
    path: Path | None
    content: str
    installed: bool
    message: str


def _default_runner(command: Sequence[str], input_text: str | None) -> CommandResult:
    return subprocess.run(
        list(command),
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
    )


def _validate_time(at: str) -> tuple[int, int]:
    if TIME_PATTERN.fullmatch(at) is None:
        raise ValueError(f"invalid schedule time {at!r}; use HH:MM (24-hour)")
    hour, minute = at.split(":")
    return int(hour), int(minute)


def _platform_name(value: str | None) -> str:
    return value if value is not None else platform.system().lower()


def _platform_kind(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"darwin", "macos"}:
        return "darwin"
    if normalized.startswith("linux"):
        return "linux"
    return normalized


def _report_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "worklog.cli",
        "report",
        "--since",
        "today",
        "--write",
        "--quiet",
    ]


def _package_parent() -> Path:
    package_file = worklog.__file__
    if package_file is None:
        raise RuntimeError("could not locate the installed worklog package")
    return Path(package_file).resolve().parent.parent


def _schedule_log_path(root: Path) -> Path:
    return root / "reports" / LOG_NAME


def _prepare_schedule_log(root: Path) -> Path:
    path = ensure_private_dir(root / "reports") / LOG_NAME
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    return path


def _manual_command() -> str:
    return shlex.join(_report_command())


def _pythonpath_assignment() -> str:
    return f"PYTHONPATH={shlex.quote(str(_package_parent()))}"


def _worklog_dir_assignment(root: Path) -> str:
    return f"WORKLOG_DIR={shlex.quote(str(root))}"


def _launch_agent_content(hour: int, minute: int, root: Path) -> str:
    log_path = str(_schedule_log_path(root))
    payload = {
        "Label": LABEL,
        "ProgramArguments": _report_command(),
        "EnvironmentVariables": {
            "PYTHONPATH": str(_package_parent()),
            "WORKLOG_DIR": str(root),
        },
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode(
        "utf-8"
    )


def _cron_line(hour: int, minute: int, root: Path) -> str:
    log_path = shlex.quote(str(_schedule_log_path(root)))
    return (
        f"{minute} {hour} * * * {_pythonpath_assignment()} "
        f"{_worklog_dir_assignment(root)} {_manual_command()} "
        f">> {log_path} 2>&1 {CRONTAB_MARKER}"
    )


def _is_worklog_cron_line(line: str) -> bool:
    return line.rstrip("\r\n").rstrip().endswith(CRONTAB_MARKER)


def _without_worklog_cron(existing: str) -> str:
    return "".join(
        line
        for line in existing.splitlines(keepends=True)
        if not _is_worklog_cron_line(line)
    )


def _with_worklog_cron(existing: str, line: str) -> str:
    content = _without_worklog_cron(existing)
    if content and not content.endswith(("\n", "\r")):
        content += "\n"
    return f"{content}{line}\n"


def _command_error(command: Sequence[str], result: CommandResult) -> RuntimeError:
    detail = (result.stderr or result.stdout or "unknown error").strip()
    return RuntimeError(f"{' '.join(command)} failed: {detail}")


def _run_checked(
    runner: Runner, command: Sequence[str], input_text: str | None = None
) -> CommandResult:
    result = runner(command, input_text)
    if result.returncode != 0:
        raise _command_error(command, result)
    return result


def _read_crontab(runner: Runner) -> str:
    command = ["crontab", "-l"]
    result = runner(command, None)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1:
        return ""
    raise _command_error(command, result)


def _write_crontab(runner: Runner, content: str) -> None:
    _run_checked(runner, ["crontab", "-"], content)


def _write_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as schedule_file:
        schedule_file.write(content)
    os.chmod(path, 0o600)


def install_schedule(
    *,
    at: str,
    platform_name: str | None = None,
    dry_run: bool = False,
    target_path: Path | None = None,
    runner: Runner | None = None,
) -> ScheduleResult:
    """Install the platform schedule, or describe it without side effects."""
    hour, minute = _validate_time(at)
    reported_platform = _platform_name(platform_name)
    kind = _platform_kind(reported_platform)
    command_runner = runner if runner is not None else _default_runner
    root = ledger_root()

    if kind == "darwin":
        path = (
            Path(target_path)
            if target_path is not None
            else Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        )
        content = _launch_agent_content(hour, minute, root)
        if dry_run:
            return ScheduleResult(
                action="install",
                platform=reported_platform,
                path=path,
                content=content,
                installed=False,
                message=f"Dry run: would install the report schedule at {path}.",
            )

        _prepare_schedule_log(root)
        _write_private_text(path, content)
        _run_checked(command_runner, ["launchctl", "load", str(path)])
        return ScheduleResult(
            action="install",
            platform=reported_platform,
            path=path,
            content=content,
            installed=True,
            message=f"Installed the report schedule at {path} for {at}.",
        )

    if kind == "linux":
        line = _cron_line(hour, minute, root)
        if dry_run:
            return ScheduleResult(
                action="install",
                platform=reported_platform,
                path=None,
                content=f"{line}\n",
                installed=False,
                message=f"Dry run: would install a crontab report schedule for {at}.",
            )

        _prepare_schedule_log(root)
        content = _with_worklog_cron(_read_crontab(command_runner), line)
        _write_crontab(command_runner, content)
        return ScheduleResult(
            action="install",
            platform=reported_platform,
            path=None,
            content=content,
            installed=True,
            message=f"Installed the crontab report schedule for {at}.",
        )

    manual = f"{_pythonpath_assignment()} {_manual_command()}"
    return ScheduleResult(
        action="install",
        platform=reported_platform,
        path=None,
        content=manual,
        installed=False,
        message=(
            f"Automatic scheduling is unsupported on {reported_platform}. "
            f"Run this command manually: {manual}"
        ),
    )


def uninstall_schedule(
    *,
    platform_name: str | None = None,
    dry_run: bool = False,
    target_path: Path | None = None,
    runner: Runner | None = None,
) -> ScheduleResult:
    """Remove the platform schedule safely, including when none is installed."""
    reported_platform = _platform_name(platform_name)
    kind = _platform_kind(reported_platform)
    command_runner = runner if runner is not None else _default_runner

    if kind == "darwin":
        path = (
            Path(target_path)
            if target_path is not None
            else Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        )
        if dry_run:
            return ScheduleResult(
                action="uninstall",
                platform=reported_platform,
                path=path,
                content="",
                installed=False,
                message=f"Dry run: would remove the report schedule at {path}.",
            )

        if not path.exists() and not path.is_symlink():
            return ScheduleResult(
                action="uninstall",
                platform=reported_platform,
                path=path,
                content="",
                installed=False,
                message=f"No report schedule is installed at {path}.",
            )

        _run_checked(command_runner, ["launchctl", "unload", str(path)])
        path.unlink(missing_ok=True)
        return ScheduleResult(
            action="uninstall",
            platform=reported_platform,
            path=path,
            content="",
            installed=False,
            message=f"Removed the report schedule at {path}.",
        )

    if kind == "linux":
        if dry_run:
            return ScheduleResult(
                action="uninstall",
                platform=reported_platform,
                path=None,
                content=CRONTAB_MARKER,
                installed=False,
                message="Dry run: would remove the marked worklog crontab line.",
            )

        existing = _read_crontab(command_runner)
        content = _without_worklog_cron(existing)
        if content == existing:
            return ScheduleResult(
                action="uninstall",
                platform=reported_platform,
                path=None,
                content=content,
                installed=False,
                message="No worklog report line is installed in the crontab.",
            )
        _write_crontab(command_runner, content)
        return ScheduleResult(
            action="uninstall",
            platform=reported_platform,
            path=None,
            content=content,
            installed=False,
            message="Removed the worklog report line from the crontab.",
        )

    return ScheduleResult(
        action="uninstall",
        platform=reported_platform,
        path=None,
        content="",
        installed=False,
        message=f"Automatic scheduling is unsupported on {reported_platform}.",
    )
