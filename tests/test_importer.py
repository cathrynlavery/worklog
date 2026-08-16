"""Tests for byte-preserving ledger imports."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from worklog.importer import import_ledger
from worklog.view import parse_session_file

from tests.support import TempLedger, permission_mode, private_mkdir, write_session


class ImporterTests(TempLedger):
    def synthetic_source(self, name: str = "source") -> Path:
        source = self.sandbox / name
        write_session(
            source,
            "codex",
            "codex-one",
            [
                ("2026-01-01T10:00:00Z", "One", "alpha", "completed"),
                ("2026-01-01T11:00:00Z", "Two", "alpha", "completed"),
                ("2026-01-01T12:00:00Z", "Three", "alpha", "partial"),
            ],
        )
        write_session(
            source,
            "codex",
            "codex-two",
            [
                ("2026-01-02T10:00:00Z", "Four", "beta", "completed"),
                ("2026-01-02T11:00:00Z", "Five", "beta", "completed"),
            ],
        )
        write_session(
            source,
            "claude",
            "claude-one",
            [
                ("2026-01-03T10:00:00Z", "Six", "gamma", "completed"),
                ("2026-01-03T11:00:00Z", "Seven", "gamma", "partial"),
            ],
        )
        return source

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_three_files_and_seven_checkpoints_import_byte_identically(self) -> None:
        source = self.synthetic_source()
        destination = self.sandbox / "destination"

        result = import_ledger(source, dest=destination)

        self.assertEqual(result.imported_files, 3)
        self.assertEqual(result.imported_checkpoints, 7)
        self.assertEqual(result.errors, [])
        source_files = sorted((source / "sessions").glob("*/*.md"))
        for source_file in source_files:
            destination_file = (
                destination
                / "sessions"
                / source_file.parent.name
                / source_file.name
            )
            self.assertEqual(self.digest(destination_file), self.digest(source_file))
            self.assertEqual(destination_file.read_bytes(), source_file.read_bytes())

    def test_second_import_is_idempotent(self) -> None:
        source = self.synthetic_source()
        destination = self.sandbox / "destination"
        first = import_ledger(source, dest=destination)

        second = import_ledger(source, dest=destination)

        self.assertEqual(first.imported_files, 3)
        self.assertEqual(second.imported_files, 0)
        self.assertEqual(second.imported_checkpoints, 0)
        self.assertEqual(second.skipped_existing, 3)

    def test_dry_run_reports_counts_without_writing_anything(self) -> None:
        source = self.synthetic_source()
        destination = self.sandbox / "dry-run-destination"

        result = import_ledger(source, dest=destination, dry_run=True)

        self.assertEqual(result.imported_files, 3)
        self.assertEqual(result.imported_checkpoints, 7)
        self.assertEqual(result.skipped_existing, 0)
        self.assertEqual(result.errors, [])
        self.assertFalse(destination.exists())

    def test_unparsable_source_is_counted_and_not_imported(self) -> None:
        source = self.sandbox / "invalid-source"
        agent_directory = private_mkdir(source / "sessions" / "codex")
        invalid = agent_directory / "invalid.md"
        invalid.write_text("not a session ledger\n", encoding="utf-8")
        destination = self.sandbox / "invalid-destination"

        result = import_ledger(source, dest=destination)

        self.assertEqual(result.imported_files, 0)
        self.assertEqual(result.skipped_unparsable, 1)
        self.assertFalse(destination.exists())

    def test_rename_conflict_creates_second_file_and_preserves_original(self) -> None:
        source = self.sandbox / "rename-source"
        source_file = write_session(
            source,
            "codex",
            "same",
            [("2026-02-01T10:00:00Z", "Original", "alpha", "completed")],
        )
        destination = self.sandbox / "rename-destination"
        import_ledger(source, dest=destination)
        original_destination = destination / "sessions" / "codex" / "same.md"
        original_bytes = original_destination.read_bytes()
        source_file = write_session(
            source,
            "codex",
            "same",
            [("2026-02-02T10:00:00Z", "Replacement", "beta", "partial")],
        )

        result = import_ledger(source, dest=destination, on_conflict="rename")

        renamed = destination / "sessions" / "codex" / "same-imported-1.md"
        self.assertEqual(result.imported_files, 1)
        self.assertEqual(original_destination.read_bytes(), original_bytes)
        self.assertEqual(renamed.read_bytes(), source_file.read_bytes())

    def test_replace_conflict_overwrites_existing_file(self) -> None:
        source = self.sandbox / "replace-source"
        source_file = write_session(
            source,
            "codex",
            "same",
            [("2026-03-01T10:00:00Z", "Original", "alpha", "completed")],
        )
        destination = self.sandbox / "replace-destination"
        import_ledger(source, dest=destination)
        destination_file = destination / "sessions" / "codex" / "same.md"
        original_bytes = destination_file.read_bytes()
        source_file = write_session(
            source,
            "codex",
            "same",
            [("2026-03-02T10:00:00Z", "Replacement", "beta", "partial")],
        )

        result = import_ledger(source, dest=destination, on_conflict="replace")

        self.assertEqual(result.imported_files, 1)
        self.assertNotEqual(destination_file.read_bytes(), original_bytes)
        self.assertEqual(destination_file.read_bytes(), source_file.read_bytes())

    def test_merge_conflict_appends_only_missing_checkpoints(self) -> None:
        source = self.sandbox / "merge-source"
        source_file = write_session(
            source,
            "codex",
            "same",
            [("2026-03-01T10:00:00Z", "Original", "alpha", "completed")],
        )
        destination = self.sandbox / "merge-destination"
        import_ledger(source, dest=destination)
        destination_file = destination / "sessions" / "codex" / "same.md"
        original_bytes = destination_file.read_bytes()
        write_session(
            source,
            "codex",
            "same",
            [
                ("2026-03-01T10:00:00Z", "Original", "alpha", "completed"),
                ("2026-03-02T10:00:00Z", "Added", "alpha", "partial"),
            ],
        )

        result = import_ledger(source, dest=destination, on_conflict="merge")

        self.assertEqual(result.imported_files, 1)
        self.assertEqual(result.imported_checkpoints, 1)
        self.assertEqual(result.errors, [])
        self.assertTrue(destination_file.read_bytes().startswith(original_bytes))
        self.assertEqual(len(parse_session_file(destination_file)), 2)

        second = import_ledger(source, dest=destination, on_conflict="merge")
        self.assertEqual(second.imported_files, 0)
        self.assertEqual(second.imported_checkpoints, 0)
        self.assertEqual(second.skipped_existing, 1)

    def test_merge_dry_run_reports_missing_checkpoints_without_writing(self) -> None:
        source = self.sandbox / "merge-dry-run-source"
        write_session(
            source,
            "codex",
            "same",
            [("2026-03-01T10:00:00Z", "Original", "alpha", "completed")],
        )
        destination = self.sandbox / "merge-dry-run-destination"
        import_ledger(source, dest=destination)
        destination_file = destination / "sessions" / "codex" / "same.md"
        original_bytes = destination_file.read_bytes()
        write_session(
            source,
            "codex",
            "same",
            [
                ("2026-03-01T10:00:00Z", "Original", "alpha", "completed"),
                ("2026-03-02T10:00:00Z", "Added", "alpha", "partial"),
            ],
        )

        result = import_ledger(
            source,
            dest=destination,
            dry_run=True,
            on_conflict="merge",
        )

        self.assertEqual(result.imported_files, 1)
        self.assertEqual(result.imported_checkpoints, 1)
        self.assertEqual(destination_file.read_bytes(), original_bytes)

    def test_merge_stops_when_an_existing_checkpoint_differs(self) -> None:
        source = self.sandbox / "merge-conflict-source"
        write_session(
            source,
            "codex",
            "same",
            [("2026-03-01T10:00:00Z", "Original", "alpha", "completed")],
        )
        destination = self.sandbox / "merge-conflict-destination"
        import_ledger(source, dest=destination)
        destination_file = destination / "sessions" / "codex" / "same.md"
        changed = destination_file.read_text(encoding="utf-8").replace(
            "Synthetic evidence.",
            "Different destination evidence.",
        )
        destination_file.write_text(changed, encoding="utf-8")
        before = destination_file.read_bytes()

        result = import_ledger(source, dest=destination, on_conflict="merge")

        self.assertEqual(result.imported_files, 0)
        self.assertEqual(result.imported_checkpoints, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("existing checkpoint differs", result.errors[0])
        self.assertEqual(destination_file.read_bytes(), before)

    def test_source_may_be_ledger_root_or_sessions_directory(self) -> None:
        source = self.synthetic_source()
        for label, source_argument in (
            ("root", source),
            ("sessions", source / "sessions"),
        ):
            with self.subTest(source=label):
                destination = self.sandbox / f"destination-{label}"
                result = import_ledger(source_argument, dest=destination)
                self.assertEqual(result.imported_files, 3)
                self.assertEqual(result.imported_checkpoints, 7)

    def test_created_directories_and_files_are_private(self) -> None:
        source = self.sandbox / "mode-source"
        write_session(
            source,
            "codex",
            "modes",
            [("2026-04-01T10:00:00Z", "Modes", "alpha", "completed")],
        )
        destination = self.sandbox / "mode-destination"

        import_ledger(source, dest=destination)

        destination_file = destination / "sessions" / "codex" / "modes.md"
        for directory in (
            destination,
            destination / "sessions",
            destination / "sessions" / "codex",
        ):
            self.assertEqual(permission_mode(directory), 0o700)
        self.assertEqual(permission_mode(destination_file), 0o600)


if __name__ == "__main__":
    unittest.main()
