"""Tests for the fail-open Claude Code prompt hook."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from worklog.cli import main as cli_main
from worklog.hook import build_response, main

from tests.support import TempLedger


class HookTests(TempLedger):
    def run_hook(self, payload: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(payload)):
            with contextlib.redirect_stdout(output):
                exit_code = main([])
        return exit_code, json.loads(output.getvalue())

    @staticmethod
    def additional_context(response: dict[str, object]) -> str:
        output = response["hookSpecificOutput"]
        assert isinstance(output, dict)
        context = output["additionalContext"]
        assert isinstance(context, str)
        return context

    def test_valid_payload_includes_session_id(self) -> None:
        exit_code, response = self.run_hook('{"session_id": "session-abc"}')

        self.assertEqual(exit_code, 0)
        output = response["hookSpecificOutput"]
        self.assertIsInstance(output, dict)
        assert isinstance(output, dict)
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn("session-abc", self.additional_context(response))

    def test_invalid_inputs_always_emit_json_and_exit_zero(self) -> None:
        cases = (
            ("malformed JSON", "{not-json"),
            ("empty stdin", ""),
            ("array payload", "[]"),
            ("missing session id", "{}"),
            ("non-string session id", '{"session_id": 123}'),
        )

        for name, payload in cases:
            with self.subTest(name=name):
                exit_code, response = self.run_hook(payload)

                self.assertEqual(exit_code, 0)
                self.assertIsInstance(response, dict)
                self.assertIn("unknown", self.additional_context(response))

    def test_instruction_names_command_and_exclusions(self) -> None:
        _, response = self.run_hook('{"session_id": "session-abc"}')
        instruction = self.additional_context(response)

        self.assertIn("worklog add", instruction)
        self.assertIn("Evidence is required", instruction)
        self.assertIn("Do not log conversational or no-op turns", instruction)
        self.assertIn("unverified claims", instruction)

    def test_hook_does_not_write_to_ledger(self) -> None:
        self.run_hook('{"session_id": "session-abc"}')

        self.assertFalse(self.root.exists())

    def test_build_response_uses_claude_code_protocol(self) -> None:
        response = build_response("session-abc")

        self.assertEqual(
            response["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        self.assertIn(
            "session-abc",
            response["hookSpecificOutput"]["additionalContext"],
        )

    def test_cli_hook_subcommand_uses_the_same_protocol(self) -> None:
        output = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO('{"session_id":"cli"}')):
            with contextlib.redirect_stdout(output):
                exit_code = cli_main(["hook"])

        self.assertEqual(exit_code, 0)
        response = json.loads(output.getvalue())
        self.assertIn("cli", self.additional_context(response))


if __name__ == "__main__":
    unittest.main()
