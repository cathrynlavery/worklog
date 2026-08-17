"""Tests for recording session checkpoints."""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest import mock

from worklog import cli
import worklog.record as record_module
from worklog.record import (
    MAX_ITEM_LENGTH,
    git_metadata,
    machine_name,
    safe_component,
)
from worklog.view import parse_session_file

from tests.support import TempLedger, permission_mode


SYNTHETIC_METADATA = {
    "project": "synthetic-project",
    "root": "/synthetic/project",
    "branch": "main",
    "commit": "abc1234",
    "working_tree": "clean",
}


class RecordTests(TempLedger):
    def record(self, **overrides: object) -> Path:
        arguments: dict[str, object] = {
            "title": "Recorded checkpoint",
            "done": ("Implemented the requested behavior.",),
            "evidence": ("Test suite passed.",),
            "agent": "codex",
            "session_id": "session-123",
            "cwd": self.sandbox,
        }
        arguments.update(overrides)
        with mock.patch.object(
            record_module, "git_metadata", return_value=SYNTHETIC_METADATA.copy()
        ):
            return record_module.record(**arguments)

    def test_same_session_appends_checkpoints_without_duplicate_header(self) -> None:
        first_path = self.record(title="First checkpoint")
        second_path = self.record(title="Second checkpoint")

        self.assertEqual(
            first_path,
            self.root / "sessions" / "codex" / "session-123.md",
        )
        self.assertEqual(second_path, first_path)
        content = first_path.read_text(encoding="utf-8")
        self.assertEqual(content.count("# Session accomplishment ledger"), 1)
        checkpoint_headings = [
            line for line in content.splitlines() if line.startswith("## ")
        ]
        self.assertEqual(len(checkpoint_headings), 2)
        self.assertIn("First checkpoint", content)
        self.assertIn("Second checkpoint", content)

    def test_record_creates_private_directories_and_file(self) -> None:
        path = self.record()

        for directory in (
            self.root,
            self.root / "sessions",
            self.root / "sessions" / "codex",
        ):
            self.assertEqual(permission_mode(directory), 0o700)
        self.assertEqual(permission_mode(path), 0o600)

    def test_status_inference_and_explicit_override(self) -> None:
        cases = (
            ("inferred-completed", (), None, "completed"),
            ("inferred-partial", ("One follow-up remains.",), None, "partial"),
            ("forced-completed", ("Still listed.",), "completed", "completed"),
            ("forced-partial", (), "partial", "partial"),
        )
        for session_id, remaining, explicit_status, expected in cases:
            with self.subTest(session_id=session_id):
                path = self.record(
                    session_id=session_id,
                    remaining=remaining,
                    status=explicit_status,
                )
                entries = parse_session_file(path)
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].status, expected)

    def test_empty_or_blank_done_items_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one done"):
            self.record(done=())
        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            self.record(done=(" \t\n ",))

    def test_missing_evidence_is_rejected_with_examples(self) -> None:
        with self.assertRaises(ValueError) as raised:
            self.record(evidence=())

        message = str(raised.exception)
        for evidence_type in ("commit SHA", "test result", "URL", "artifact path"):
            with self.subTest(evidence_type=evidence_type):
                self.assertIn(evidence_type, message)

    def test_allow_no_evidence_writes_existing_placeholder(self) -> None:
        path = self.record(evidence=(), allow_no_evidence=True)

        content = path.read_text(encoding="utf-8")
        self.assertIn("### Evidence\n\n- None recorded.", content)

    def test_record_with_evidence_still_succeeds(self) -> None:
        path = self.record(evidence=("Artifact: build/report.html",))

        content = path.read_text(encoding="utf-8")
        self.assertIn("### Evidence\n\n- Artifact: build/report.html", content)

    def test_blank_evidence_item_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be blank"):
            self.record(evidence=(" \t\n ",))

    def test_overlong_item_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "keep it under"):
            self.record(done=("x" * (MAX_ITEM_LENGTH + 1),))

    def test_safe_component_sanitizes_and_truncates(self) -> None:
        self.assertEqual(safe_component("../..", "fallback"), "fallback")
        self.assertEqual(safe_component("two words", "fallback"), "two-words")
        self.assertEqual(safe_component("one/two", "fallback"), "one-two")
        self.assertEqual(len(safe_component("x" * 200, "fallback")), 120)

    def test_git_metadata_handles_non_repository(self) -> None:
        directory = self.sandbox / "not-a-repository"
        directory.mkdir()

        metadata = git_metadata(directory)

        self.assertEqual(metadata["branch"], "not a Git repository")
        self.assertEqual(metadata["root"], str(directory))

    def test_machine_name_prefers_explicit_override(self) -> None:
        with mock.patch.dict(os.environ, {"WORKLOG_MACHINE": "Silverfox"}):
            self.assertEqual(machine_name(), "Silverfox")

    def test_machine_name_uses_macos_computer_name(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(record_module.platform, "system", return_value="Darwin"),
            mock.patch.object(record_module, "run", return_value="Silverfox"),
        ):
            self.assertEqual(machine_name(), "Silverfox")

    def test_machine_name_falls_back_to_platform_node(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(record_module.platform, "system", return_value="Linux"),
            mock.patch.object(record_module.platform, "node", return_value="worker-1"),
        ):
            self.assertEqual(machine_name(), "worker-1")

    def test_evidence_is_redacted_before_writing(self) -> None:
        token = "sk-" + "r" * 24

        path = self.record(evidence=(f"Observed token {token}",))

        content = path.read_text(encoding="utf-8")
        self.assertNotIn(token, content)
        self.assertIn("[REDACTED TOKEN]", content)

    def test_agent_inference_from_codex_thread_id(self) -> None:
        os.environ["CODEX_THREAD_ID"] = "codex-thread"

        path = self.record(agent=None, session_id=None)

        self.assertEqual(path.parent.name, "codex")
        self.assertEqual(path.name, "codex-thread.md")

    def test_agent_inference_from_claude_session_id(self) -> None:
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", os.environ)
        os.environ["CLAUDE_SESSION_ID"] = "claude-session"

        path = self.record(agent=None, session_id=None)

        self.assertEqual(path.parent.name, "claude")
        self.assertEqual(path.name, "claude-session.md")

    def test_cli_requires_evidence_unless_explicitly_allowed(self) -> None:
        common = [
            "add",
            "--title",
            "t",
            "--done",
            "d",
            "--cwd",
            str(self.sandbox),
        ]
        output = io.StringIO()
        errors = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            missing_evidence_code = cli.main(common)
        self.assertEqual(missing_evidence_code, 2)
        self.assertIn("evidence is required", errors.getvalue())
        self.assertFalse(self.root.exists())

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            evidence_code = cli.main([*common, "--evidence", "e"])
            allowed_code = cli.main([*common, "--allow-no-evidence"])
        self.assertEqual(evidence_code, 0)
        self.assertEqual(allowed_code, 0)


if __name__ == "__main__":
    unittest.main()
