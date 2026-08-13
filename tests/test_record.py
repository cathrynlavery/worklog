"""Tests for recording session checkpoints."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import worklog.record as record_module
from worklog.record import MAX_ITEM_LENGTH, git_metadata, safe_component
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


if __name__ == "__main__":
    unittest.main()
