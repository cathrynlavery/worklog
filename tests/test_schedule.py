"""Tests for hermetic report schedule installation and removal."""

from __future__ import annotations

import datetime as dt
import os
import plistlib
import shlex
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

import worklog

from worklog.paths import reports_dir
from worklog.schedule import install_schedule, uninstall_schedule

from tests.support import TempLedger, permission_mode, write_session


class FakeRunner:
    """Record scheduler commands without touching launchd or the real crontab."""

    def __init__(self, crontab: str = "") -> None:
        self.crontab = crontab
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self, command: Sequence[str], input_text: str | None
    ) -> subprocess.CompletedProcess[str]:
        arguments = list(command)
        self.calls.append((arguments, input_text))
        if arguments == ["crontab", "-l"]:
            return subprocess.CompletedProcess(arguments, 0, self.crontab, "")
        if arguments == ["crontab", "-"]:
            self.crontab = input_text or ""
        return subprocess.CompletedProcess(arguments, 0, "", "")


class ScheduleTests(TempLedger):
    def test_time_validation_accepts_full_day_boundaries(self) -> None:
        for value in ("00:00", "23:59"):
            with self.subTest(value=value):
                result = install_schedule(
                    at=value, platform_name="unsupported", dry_run=True
                )
                self.assertFalse(result.installed)

    def test_time_validation_rejects_non_hhmm_values(self) -> None:
        for value in ("9:00", "24:00", "abc", ""):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "HH:MM"):
                    install_schedule(
                        at=value, platform_name="unsupported", dry_run=True
                    )

    def test_macos_dry_run_returns_plist_without_writes_or_commands(self) -> None:
        target = self.sandbox / "LaunchAgents" / "com.worklog.report.plist"
        runner = FakeRunner()

        result = install_schedule(
            at="21:05",
            platform_name="darwin",
            dry_run=True,
            target_path=target,
            runner=runner,
        )

        self.assertFalse(target.exists())
        self.assertEqual(runner.calls, [])
        self.assertEqual(result.path, target)
        self.assertIn("<key>Hour</key>", result.content)
        self.assertIn("<integer>21</integer>", result.content)
        self.assertIn("worklog.cli", result.content)
        self.assertIn("--quiet", result.content)
        payload = plistlib.loads(result.content.encode("utf-8"))
        package_parent = Path(worklog.__file__).resolve().parent.parent
        self.assertEqual(
            payload["EnvironmentVariables"]["PYTHONPATH"], str(package_parent)
        )
        self.assertEqual(
            payload["EnvironmentVariables"]["WORKLOG_DIR"], str(self.root)
        )
        self.assertTrue((package_parent / "worklog" / "__init__.py").is_file())
        log_path = str(reports_dir() / "schedule.log")
        self.assertEqual(payload["StandardOutPath"], log_path)
        self.assertEqual(payload["StandardErrorPath"], log_path)
        self.assertFalse(reports_dir().exists())

    def test_linux_dry_run_returns_crontab_without_commands(self) -> None:
        runner = FakeRunner("15 4 * * * unrelated\n")

        result = install_schedule(
            at="00:00", platform_name="linux", dry_run=True, runner=runner
        )

        self.assertEqual(runner.calls, [])
        self.assertIn("0 0 * * *", result.content)
        self.assertIn("# worklog-report", result.content)
        self.assertIn("-m worklog.cli report", result.content)
        package_parent = Path(worklog.__file__).resolve().parent.parent
        self.assertIn(f"PYTHONPATH={package_parent}", result.content)
        self.assertIn(f"WORKLOG_DIR={self.root}", result.content)
        self.assertIn(f">> {reports_dir() / 'schedule.log'} 2>&1", result.content)
        self.assertFalse(reports_dir().exists())

    def test_linux_cron_quotes_ledger_path_containing_a_space(self) -> None:
        root_with_space = self.sandbox / "custom ledger"
        os.environ["WORKLOG_DIR"] = str(root_with_space)

        result = install_schedule(
            at="18:00", platform_name="linux", dry_run=True
        )

        quoted_root = shlex.quote(str(root_with_space))
        quoted_log = shlex.quote(str(root_with_space / "reports" / "schedule.log"))
        self.assertIn(f"WORKLOG_DIR={quoted_root}", result.content)
        self.assertIn(f">> {quoted_log} 2>&1", result.content)

    def test_macos_install_writes_injected_path_and_uninstall_removes_it(self) -> None:
        target = self.sandbox / "LaunchAgents" / "com.worklog.report.plist"
        runner = FakeRunner()

        installed = install_schedule(
            at="20:30",
            platform_name="darwin",
            target_path=target,
            runner=runner,
        )

        self.assertTrue(installed.installed)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), installed.content)
        self.assertEqual(
            runner.calls[0], (["launchctl", "load", str(target)], None)
        )
        log_path = reports_dir() / "schedule.log"
        self.assertTrue(log_path.is_file())
        self.assertEqual(permission_mode(log_path.parent), 0o700)
        self.assertEqual(permission_mode(log_path), 0o600)

        removed = uninstall_schedule(
            platform_name="darwin", target_path=target, runner=runner
        )

        self.assertFalse(removed.installed)
        self.assertFalse(target.exists())
        self.assertEqual(
            runner.calls[1], (["launchctl", "unload", str(target)], None)
        )

    def test_generated_argv_uses_baked_ledger_and_writes_report(self) -> None:
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        timestamp = now.isoformat().replace("+00:00", "Z")
        write_session(
            self.root,
            "codex",
            "scheduled-run",
            [(timestamp, "Scheduled checkpoint", "alpha", "completed")],
        )
        target = self.sandbox / "LaunchAgents" / "com.worklog.report.plist"
        schedule = install_schedule(
            at="21:05",
            platform_name="darwin",
            dry_run=True,
            target_path=target,
        )
        payload = plistlib.loads(schedule.content.encode("utf-8"))
        arguments = payload["ProgramArguments"]
        self.assertEqual(arguments[0], sys.executable)
        other_root = self.sandbox / "other-ledger"
        environment = os.environ.copy()
        environment["WORKLOG_DIR"] = str(other_root)
        environment.update(payload["EnvironmentVariables"])

        completed = subprocess.run(
            arguments,
            cwd="/",
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        day = dt.datetime.now().astimezone().date()
        report_path = reports_dir() / f"{day.isoformat()}.md"
        self.assertTrue(report_path.is_file())
        self.assertIn(
            "Scheduled checkpoint", report_path.read_text(encoding="utf-8")
        )
        self.assertFalse((other_root / "reports" / report_path.name).exists())

    def test_macos_uninstall_with_nothing_installed_is_a_noop(self) -> None:
        target = self.sandbox / "missing" / "com.worklog.report.plist"
        runner = FakeRunner()

        result = uninstall_schedule(
            platform_name="darwin", target_path=target, runner=runner
        )

        self.assertFalse(result.installed)
        self.assertEqual(runner.calls, [])
        self.assertIn("No report schedule", result.message)

    def test_crontab_uninstall_preserves_every_unrelated_line(self) -> None:
        unrelated = (
            "# keep this comment\n"
            "15 4 * * * /usr/bin/backup\n"
            "30 20 * * * /usr/bin/python -m worklog.cli report "
            "--since today --write --quiet # worklog-report\n"
            "0 6 * * 1 /usr/bin/weekly\n"
        )
        expected = (
            "# keep this comment\n"
            "15 4 * * * /usr/bin/backup\n"
            "0 6 * * 1 /usr/bin/weekly\n"
        )
        runner = FakeRunner(unrelated)

        result = uninstall_schedule(platform_name="linux", runner=runner)

        self.assertFalse(result.installed)
        self.assertEqual(runner.crontab, expected)
        self.assertEqual(result.content, expected)
        self.assertEqual(runner.calls[0], (["crontab", "-l"], None))
        self.assertEqual(runner.calls[1], (["crontab", "-"], expected))

    def test_linux_uninstall_with_no_crontab_line_is_a_noop(self) -> None:
        existing = "15 4 * * * /usr/bin/backup\n"
        runner = FakeRunner(existing)

        result = uninstall_schedule(platform_name="linux", runner=runner)

        self.assertEqual(runner.calls, [(["crontab", "-l"], None)])
        self.assertEqual(result.content, existing)
        self.assertIn("No worklog report line", result.message)

    def test_unsupported_platform_explains_manual_command(self) -> None:
        runner = FakeRunner()

        result = install_schedule(
            at="19:15", platform_name="plan9", runner=runner
        )

        self.assertFalse(result.installed)
        self.assertIsNone(result.path)
        self.assertEqual(runner.calls, [])
        self.assertIn("unsupported", result.message)
        self.assertIn(
            "-m worklog.cli report --since today --write --quiet", result.message
        )


if __name__ == "__main__":
    unittest.main()
