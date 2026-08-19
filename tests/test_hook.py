"""Tests for the fail-open Claude Code prompt hook."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from worklog.cli import main as cli_main
from worklog.hook import build_context, build_response, build_terse_context, main

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

    def test_first_turn_is_full_and_repeat_turns_are_terse(self) -> None:
        _, first = self.run_hook('{"session_id": "session-abc"}')
        _, second = self.run_hook('{"session_id": "session-abc"}')

        self.assertEqual(self.additional_context(first), build_context("session-abc"))
        self.assertEqual(
            self.additional_context(second),
            build_terse_context("session-abc"),
        )

    def test_terse_reminder_keeps_the_command_and_the_session_id(self) -> None:
        self.run_hook('{"session_id": "session-abc"}')
        _, response = self.run_hook('{"session_id": "session-abc"}')
        reminder = self.additional_context(response)

        self.assertIn("worklog add", reminder)
        self.assertIn("session-abc", reminder)
        self.assertIn("Evidence is required", reminder)

    def test_terse_reminder_is_substantially_shorter(self) -> None:
        session_id = "cceecc41-d8a4-41b8-8fb8-9939d6dcf66e"

        full = build_context(session_id)
        terse = build_terse_context(session_id)

        self.assertLess(len(terse), len(full) // 2)

    def test_unknown_session_never_degrades_to_the_terse_reminder(self) -> None:
        for _ in range(3):
            _, response = self.run_hook("{}")
            self.assertEqual(self.additional_context(response), build_context("unknown"))

    def test_parallel_sessions_each_receive_the_full_instruction(self) -> None:
        _, first = self.run_hook('{"session_id": "session-one"}')
        _, second = self.run_hook('{"session_id": "session-two"}')

        self.assertEqual(self.additional_context(first), build_context("session-one"))
        self.assertEqual(self.additional_context(second), build_context("session-two"))

    def test_session_id_is_shell_quoted_in_both_forms(self) -> None:
        payload = json.dumps({"session_id": "a'b"})
        _, first = self.run_hook(payload)
        _, second = self.run_hook(payload)

        for response in (first, second):
            self.assertIn("""'a'"'"'b'""", self.additional_context(response))

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
