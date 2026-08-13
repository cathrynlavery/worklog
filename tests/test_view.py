"""Tests for parsing, collecting, filtering, and rendering checkpoints."""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from worklog.view import (
    Entry,
    _parse_timestamp,
    collect_entries,
    filter_entries,
    parse_session_file,
    parse_since,
    render,
)

from tests.support import TempLedger, write_session


class ViewTests(TempLedger):
    def test_session_with_three_checkpoints_yields_three_entries(self) -> None:
        path = write_session(
            self.root,
            "codex",
            "three-checkpoints",
            [
                ("2026-01-01T10:00:00Z", "First", "alpha", "completed"),
                ("2026-01-01T11:00:00Z", "Second", "alpha", "partial"),
                ("2026-01-01T12:00:00Z", "Third", "alpha", "completed"),
            ],
        )

        entries = parse_session_file(path)

        self.assertEqual(len(entries), 3)
        self.assertEqual([entry.title for entry in entries], ["First", "Second", "Third"])

    def test_entries_sort_newest_first_across_files(self) -> None:
        write_session(
            self.root,
            "codex",
            "one",
            [("2026-02-01T10:00:00Z", "Middle", "alpha", "completed")],
        )
        write_session(
            self.root,
            "claude",
            "two",
            [
                ("2026-02-01T09:00:00Z", "Oldest", "beta", "completed"),
                ("2026-02-01T11:00:00Z", "Newest", "beta", "completed"),
            ],
        )

        entries = collect_entries(self.root)

        self.assertEqual(
            [entry.title for entry in entries], ["Newest", "Middle", "Oldest"]
        )

    def test_project_and_status_come_from_each_checkpoint(self) -> None:
        path = write_session(
            self.root,
            "codex",
            "changing-metadata",
            [
                ("2026-03-01T10:00:00Z", "Alpha", "project-a", "completed"),
                ("2026-03-01T11:00:00Z", "Beta", "project-b", "partial"),
                ("2026-03-01T12:00:00Z", "Gamma", "project-c", "completed"),
            ],
        )

        entries = parse_session_file(path)

        self.assertEqual(
            [(entry.project, entry.status) for entry in entries],
            [
                ("project-a", "completed"),
                ("project-b", "partial"),
                ("project-c", "completed"),
            ],
        )

    def test_numeric_offset_timestamp_sorts_with_z_timestamps(self) -> None:
        write_session(
            self.root,
            "codex",
            "offsets",
            [
                ("2026-04-01T07:30:00Z", "Before", "alpha", "completed"),
                ("2026-04-01T01:00:00-07:00", "Offset", "alpha", "completed"),
                ("2026-04-01T08:30:00Z", "After", "alpha", "completed"),
            ],
        )

        entries = collect_entries(self.root)

        self.assertEqual([entry.title for entry in entries], ["After", "Offset", "Before"])

    def test_timestamp_without_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            _parse_timestamp("2026-01-01T12:00:00")

        path = write_session(
            self.root,
            "codex",
            "naive",
            [("2026-01-01T12:00:00", "Naive", "alpha", "completed")],
        )
        self.assertEqual(parse_session_file(path), [])

    def test_headerless_file_uses_filename_as_session_id(self) -> None:
        path = write_session(
            self.root,
            "codex",
            "filename-session",
            [("2026-01-01T12:00:00Z", "Headerless", "alpha", "completed")],
        )
        text = path.read_text(encoding="utf-8")
        path.write_text(text[text.index("## ") :], encoding="utf-8")

        entries = parse_session_file(path)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].session_id, "filename-session")

    def test_truncated_final_block_is_skipped_but_earlier_block_survives(self) -> None:
        path = write_session(
            self.root,
            "codex",
            "truncated",
            [
                ("2026-01-01T10:00:00Z", "Complete", "alpha", "completed"),
                ("2026-01-01T11:00:00Z", "Truncated", "alpha", "partial"),
            ],
        )
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rsplit("---\n\n", 1)[0], encoding="utf-8")

        entries = parse_session_file(path)

        self.assertEqual([entry.title for entry in entries], ["Complete"])

    def test_file_without_checkpoints_yields_no_entries(self) -> None:
        path = self.sandbox / "empty.md"
        path.write_text("# Session accomplishment ledger\n", encoding="utf-8")

        self.assertEqual(parse_session_file(path), [])

    def test_unreadable_file_yields_no_entries(self) -> None:
        path = self.sandbox / "unreadable.md"
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(parse_session_file(path), [])

    def test_parse_since_supported_values(self) -> None:
        local_today = dt.datetime.now().astimezone().date()
        expected_today = dt.datetime.combine(local_today, dt.time.min).astimezone(
            dt.timezone.utc
        )
        expected_yesterday = dt.datetime.combine(
            local_today - dt.timedelta(days=1), dt.time.min
        ).astimezone(dt.timezone.utc)
        self.assertEqual(parse_since("today"), expected_today)
        self.assertEqual(parse_since("yesterday"), expected_yesterday)

        for value, delta in (
            ("week", dt.timedelta(days=7)),
            ("month", dt.timedelta(days=30)),
            ("3d", dt.timedelta(days=3)),
            ("6h", dt.timedelta(hours=6)),
        ):
            with self.subTest(value=value):
                before = dt.datetime.now(dt.timezone.utc) - delta
                parsed = parse_since(value)
                after = dt.datetime.now(dt.timezone.utc) - delta
                self.assertLessEqual(before, parsed)
                self.assertLessEqual(parsed, after)

        iso_day = dt.date(2025, 12, 25)
        expected_iso = dt.datetime.combine(iso_day, dt.time.min).astimezone(
            dt.timezone.utc
        )
        self.assertEqual(parse_since("2025-12-25"), expected_iso)

    def test_parse_since_rejects_garbage(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid --since"):
            parse_since("eventually")

    def test_filter_entries_by_since_agent_and_project(self) -> None:
        entries = [
            Entry(
                timestamp="2026-05-01T08:00:00Z",
                agent="codex",
                project="alpha",
                title="Old alpha",
                status="completed",
                path="/synthetic/one.md",
                session_id="one",
            ),
            Entry(
                timestamp="2026-05-02T08:00:00Z",
                agent="claude",
                project="beta",
                title="New beta",
                status="partial",
                path="/synthetic/two.md",
                session_id="two",
            ),
            Entry(
                timestamp="2026-05-03T08:00:00Z",
                agent="codex",
                project="beta",
                title="Newest beta",
                status="completed",
                path="/synthetic/three.md",
                session_id="three",
            ),
        ]

        since = dt.datetime(2026, 5, 2, tzinfo=dt.timezone.utc)
        self.assertEqual(
            [entry.title for entry in filter_entries(entries, since=since)],
            ["New beta", "Newest beta"],
        )
        self.assertEqual(
            [entry.title for entry in filter_entries(entries, agent="codex")],
            ["Old alpha", "Newest beta"],
        )
        self.assertEqual(
            [entry.title for entry in filter_entries(entries, project="beta")],
            ["New beta", "Newest beta"],
        )

    def test_render_includes_entry_and_optional_path(self) -> None:
        entry = Entry(
            timestamp="2026-05-03T08:00:00Z",
            agent="codex",
            project="alpha",
            title="Rendered",
            status="completed",
            path="/synthetic/session.md",
            session_id="session",
        )

        self.assertIn("Rendered", render([entry]))
        self.assertIn(entry.path, render([entry]))
        self.assertNotIn(entry.path, render([entry], show_path=False))


if __name__ == "__main__":
    unittest.main()
