"""Tests for built-in and external redaction."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from worklog.redact import redact

from tests.support import TempLedger


class RedactionTests(TempLedger):
    def assert_redacted(self, secret: str) -> None:
        result = redact(secret)
        self.assertNotEqual(result, secret)
        self.assertNotIn(secret, result)
        self.assertIn("REDACTED", result)

    def test_each_sensitive_pattern_class_is_redacted(self) -> None:
        private_key = (
            "-----BEGIN " + "PRIVATE KEY-----\nprivate-material\n"
            "-----END " + "PRIVATE KEY-----"
        )
        token_cases = (
            private_key,
            "Bearer " + "sensitive.value-123",
            "sk-" + "a" * 24,
            "ghp_" + "b" * 24,
            "github_pat_" + "c" * 24,
            "AKIA" + "D" * 16,
        )
        for value in token_cases:
            with self.subTest(value=value[:12]):
                self.assert_redacted(value)

        for name in ("secret", "token", "password", "api_key"):
            with self.subTest(assignment=name):
                self.assert_redacted(f"{name}=" + "sensitive-value")

    def test_ordinary_content_passes_through_unchanged(self) -> None:
        ordinary_values = (
            "abc1234",
            "0123456789abcdef0123456789abcdef01234567",
            "https://github.com/example/worklog",
            "Processed 17 files and found 2048 useful records.",
            "/Users/example/Developer/worklog/report.md",
        )
        for value in ordinary_values:
            with self.subTest(value=value):
                self.assertEqual(redact(value), value)

    def _redactor(self, body: str, *, executable: bool = True) -> Path:
        path = self.sandbox / "redactor.sh"
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        os.chmod(path, 0o700 if executable else 0o600)
        os.environ["WORKLOG_REDACTOR"] = str(path)
        return path

    def test_successful_nonempty_override_is_used(self) -> None:
        self._redactor("printf 'external result\\n'\n")

        self.assertEqual(redact("ordinary input"), "external result")

    def test_successful_empty_override_falls_back_to_builtin(self) -> None:
        self._redactor("exit 0\n")
        token = "sk-" + "e" * 24

        result = redact(token)

        self.assertNotIn(token, result)
        self.assertIn("REDACTED", result)

    def test_nonzero_override_falls_back_to_builtin(self) -> None:
        self._redactor("exit 9\n")
        token = "ghp_" + "f" * 24

        self.assert_redacted(token)

    def test_missing_or_nonexecutable_override_falls_back(self) -> None:
        token = "github_pat_" + "g" * 24
        targets = (self.sandbox / "missing-redactor", self._redactor("exit 0\n", executable=False))
        for target in targets:
            with self.subTest(target=target.name):
                os.environ["WORKLOG_REDACTOR"] = str(target)
                self.assert_redacted(token)


if __name__ == "__main__":
    unittest.main()
