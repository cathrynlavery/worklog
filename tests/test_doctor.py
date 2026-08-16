"""Tests for resilient, non-disclosing diagnostics."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest import mock

from worklog.cli import main
from worklog.doctor import Check, render_checks, run_checks, worst_status

from tests.support import TempLedger, private_mkdir, write_session


class DoctorTests(TempLedger):
    @staticmethod
    def named(checks: list[Check], name: str) -> Check:
        return next(check for check in checks if check.name == name)

    def assert_marker_not_disclosed(self, checks: list[Check], marker: str) -> None:
        for check in checks:
            self.assertNotIn(marker, check.name)
            self.assertNotIn(marker, check.message)
            self.assertNotIn(marker, check.hint or "")
        self.assertNotIn(marker, render_checks(checks))

    def test_run_checks_handles_missing_root(self) -> None:
        self.assertFalse(self.root.exists())

        checks = run_checks()

        self.assertEqual(len(checks), 9)
        self.assertEqual(self.named(checks, "ledger root").status, "ok")

    def test_run_checks_handles_root_that_is_a_file(self) -> None:
        self.root.write_text("not a directory", encoding="utf-8")

        checks = run_checks()

        ledger_check = self.named(checks, "ledger root")
        self.assertEqual(ledger_check.status, "fail")
        self.assertIn("not a directory", ledger_check.message)

    def test_run_checks_handles_broken_root_symlink(self) -> None:
        self.root.symlink_to(self.sandbox / "missing-target", target_is_directory=True)

        checks = run_checks()

        ledger_check = self.named(checks, "ledger root")
        self.assertEqual(ledger_check.status, "fail")
        self.assertIn("broken symlink", ledger_check.message)

    def test_run_checks_handles_unreadable_sessions_directory(self) -> None:
        self.root.mkdir(mode=0o700)
        sessions = self.root / "sessions"
        sessions.mkdir(mode=0o700)
        os.chmod(sessions, 0o000)
        try:
            checks = run_checks()
        finally:
            os.chmod(sessions, 0o700)

        self.assertEqual(len(checks), 9)
        self.assertIn(self.named(checks, "ledger contents").status, {"ok", "warn"})

    def test_run_checks_handles_malformed_settings_json(self) -> None:
        claude_directory = private_mkdir(self.home / ".claude")
        (claude_directory / "settings.json").write_text("{malformed", encoding="utf-8")

        checks = run_checks()

        hook_check = self.named(checks, "claude code hook")
        self.assertEqual(hook_check.status, "warn")
        self.assertIn("malformed JSON", hook_check.message)

    def test_loose_permissions_warn_instead_of_fail(self) -> None:
        session_file = write_session(
            self.root,
            "codex",
            "loose",
            [("2026-01-01T10:00:00Z", "Loose", "alpha", "completed")],
        )
        os.chmod(self.root, 0o755)
        os.chmod(self.root / "sessions", 0o755)
        os.chmod(session_file.parent, 0o755)
        os.chmod(session_file, 0o644)

        permissions = self.named(run_checks(), "permissions")

        self.assertEqual(permissions.status, "warn")
        self.assertNotEqual(permissions.status, "fail")
        self.assertIn("0700/0600", permissions.message)

    def test_claude_settings_contents_are_never_disclosed(self) -> None:
        marker = "SYNTHETIC-SETTINGS-CONTENT-MUST-NOT-LEAK"
        claude_directory = private_mkdir(self.home / ".claude")
        settings = claude_directory / "settings.json"
        cases = (
            (
                "valid without hook",
                '{"marker": "' + marker + '", "hooks": {}}',
                "warn",
                "No worklog UserPromptSubmit hook",
            ),
            (
                "malformed",
                '{"marker": "' + marker + '", "hooks": {',
                "warn",
                "malformed JSON",
            ),
            (
                "valid with worklog hook",
                (
                    '{"marker": "'
                    + marker
                    + '", "hooks": {"UserPromptSubmit": '
                    '[{"hooks": [{"command": "python3 -m worklog.hook"}]}]}}'
                ),
                "ok",
                "emits valid Claude Code context",
            ),
            (
                "worklog command is not a prompt hook",
                (
                    '{"marker": "'
                    + marker
                    + '", "hooks": {"UserPromptSubmit": '
                    '[{"hooks": [{"command": "worklog add"}]}]}}'
                ),
                "warn",
                "No worklog UserPromptSubmit hook",
            ),
        )

        for case, content, expected_status, expected_message in cases:
            with self.subTest(case=case):
                settings.write_text(content, encoding="utf-8")

                checks = run_checks()
                hook_check = self.named(checks, "claude code hook")

                self.assertEqual(hook_check.status, expected_status)
                self.assertIn(expected_message, hook_check.message)
                self.assert_marker_not_disclosed(checks, marker)

    def test_claude_hook_protocol_failure_is_reported(self) -> None:
        claude_directory = private_mkdir(self.home / ".claude")
        settings = claude_directory / "settings.json"
        settings.write_text(
            '{"hooks": {"UserPromptSubmit": '
            '[{"hooks": [{"command": "python3 -m worklog.hook"}]}]}}',
            encoding="utf-8",
        )

        with mock.patch(
            "worklog.doctor.build_response",
            return_value={"additionalContext": "worklog add"},
        ):
            hook_check = self.named(run_checks(), "claude code hook")

        self.assertEqual(hook_check.status, "warn")
        self.assertIn("does not match", hook_check.message)

    def test_codex_adapter_contents_are_never_disclosed(self) -> None:
        marker = "SYNTHETIC-CODEX-CONTENT-MUST-NOT-LEAK"
        codex_directory = private_mkdir(self.home / ".codex")
        instructions = codex_directory / "AGENTS.md"
        cases = (
            ("mentions worklog", marker + "\nUse worklog checkpoints.\n", "ok"),
            ("does not mention worklog", marker + "\nNo adapter configured.\n", "warn"),
        )

        for case, content, expected_status in cases:
            with self.subTest(case=case):
                instructions.write_text(content, encoding="utf-8")

                checks = run_checks()
                adapter_check = self.named(checks, "codex adapter")

                self.assertEqual(adapter_check.status, expected_status)
                self.assert_marker_not_disclosed(checks, marker)

    def test_writability_probe_leaves_no_file_behind(self) -> None:
        self.root.mkdir(mode=0o700)
        sentinel = self.root / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        before = {path.name for path in self.root.iterdir()}

        checks = run_checks()

        after = {path.name for path in self.root.iterdir()}
        self.assertEqual(after, before)
        self.assertFalse(any(name.startswith(".worklog-doctor-") for name in after))
        self.assertEqual(self.named(checks, "ledger root").status, "ok")

    def test_worst_status_and_cli_exit_code_mapping(self) -> None:
        warning = [Check("example", "warn", "warning only")]
        failure = [Check("example", "fail", "failure")]
        self.assertEqual(worst_status([]), "ok")
        self.assertEqual(worst_status(warning), "warn")
        self.assertEqual(worst_status(failure), "fail")

        output = io.StringIO()
        with mock.patch("worklog.cli.run_checks", return_value=warning):
            with contextlib.redirect_stdout(output):
                warning_code = main(["doctor"])
        with mock.patch("worklog.cli.run_checks", return_value=failure):
            with contextlib.redirect_stdout(output):
                failure_code = main(["doctor"])

        self.assertEqual(warning_code, 0)
        self.assertEqual(failure_code, 1)


if __name__ == "__main__":
    unittest.main()
