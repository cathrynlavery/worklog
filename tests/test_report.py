"""Tests for Markdown worklog reports and report CLI behavior."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import unittest

from worklog.cli import main
from worklog.paths import reports_dir
from worklog.report import build_report, write_report
from worklog.view import Entry, collect_entries, filter_entries, parse_since

from tests.support import TempLedger, permission_mode, write_session


class ReportTests(TempLedger):
    def test_groups_busiest_project_first_and_counts_entities(self) -> None:
        write_session(
            self.root,
            "codex",
            "alpha-one",
            [
                ("2026-08-13T09:00:00Z", "Alpha older", "alpha", "completed"),
                ("2026-08-13T11:00:00Z", "Alpha newer", "alpha", "completed"),
            ],
        )
        write_session(
            self.root,
            "claude",
            "beta-one",
            [("2026-08-13T12:00:00Z", "Beta only", "beta", "completed")],
        )
        since = parse_since("2026-08-13")
        until = parse_since("2026-08-14")

        report = build_report(collect_entries(), since=since, until=until)

        self.assertIn("3 checkpoints across 2 projects and 2 agents.", report)
        self.assertLess(report.index("## alpha"), report.index("## beta"))
        self.assertLess(report.index("Alpha newer"), report.index("Alpha older"))

    def test_collects_remaining_items_with_their_projects(self) -> None:
        alpha = write_session(
            self.root,
            "codex",
            "alpha-open",
            [("2026-08-13T10:00:00Z", "Alpha", "alpha", "partial")],
        )
        beta = write_session(
            self.root,
            "claude",
            "beta-open",
            [("2026-08-13T11:00:00Z", "Beta", "beta", "partial")],
        )
        alpha.write_text(
            alpha.read_text(encoding="utf-8").replace(
                "- None recorded.\n\n---", "- [ ] Ship alpha.\n\n---"
            ),
            encoding="utf-8",
        )
        beta.write_text(
            beta.read_text(encoding="utf-8").replace(
                "- None recorded.\n\n---", "- [ ] Review beta.\n\n---"
            ),
            encoding="utf-8",
        )
        since = parse_since("2026-08-13")

        report = build_report(
            collect_entries(), since=since, until=since + dt.timedelta(hours=23)
        )

        self.assertIn("## Still open", report)
        self.assertIn("- [ ] Ship alpha. (alpha)", report)
        self.assertIn("- [ ] Review beta. (beta)", report)

    def test_empty_window_is_a_valid_report(self) -> None:
        since = parse_since("2026-08-13")

        report = build_report([], since=since, until=since)

        self.assertTrue(report.startswith("# Worklog — 2026-08-13\n"))
        self.assertIn("0 checkpoints across 0 projects and 0 agents.", report)
        self.assertIn("Nothing was recorded in this window.", report)
        self.assertIn("No remaining items were recorded.", report)

    def test_report_strips_ansi_colour_and_emoji(self) -> None:
        since = parse_since("2026-08-13")
        entry = Entry(
            timestamp="2026-08-13T12:00:00Z",
            agent="codex",
            project="alpha 🚀",
            title="\x1b[31mFinished\x1b[0m 🚀",
            status="completed",
            path=str(self.sandbox / "missing.md"),
            session_id="plain",
        )

        report = build_report(
            [entry], since=since, until=since + dt.timedelta(hours=23)
        )

        self.assertNotIn("\x1b", report)
        self.assertNotIn("🚀", report)
        self.assertIn("Finished", report)

    def test_write_is_private_and_overwrites_existing_report(self) -> None:
        day = dt.date(2026, 8, 13)

        path = write_report("first\n", day=day)
        second_path = write_report("second\n", day=day)

        self.assertEqual(path, reports_dir() / "2026-08-13.md")
        self.assertEqual(second_path, path)
        self.assertEqual(path.read_text(encoding="utf-8"), "second\n")
        self.assertEqual(permission_mode(path), 0o600)
        self.assertEqual(permission_mode(path.parent), 0o700)

    def test_cli_write_is_quiet_private_and_idempotent(self) -> None:
        write_session(
            self.root,
            "codex",
            "cli-report",
            [("2026-08-13T12:00:00Z", "CLI item", "alpha", "completed")],
        )
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            status = main(
                [
                    "report",
                    "--since",
                    "2026-08-13",
                    "--until",
                    "2026-08-14",
                    "--write",
                    "--quiet",
                ]
            )

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "")
        day = dt.datetime.now().astimezone().date()
        path = reports_dir() / f"{day.isoformat()}.md"
        original = path.read_text(encoding="utf-8")
        path.write_text(f"{original}SHOULD BE OVERWRITTEN\n", encoding="utf-8")

        with contextlib.redirect_stdout(output):
            self.assertEqual(
                main(
                    [
                        "report",
                        "--since",
                        "2026-08-13",
                        "--until",
                        "2026-08-14",
                        "--write",
                        "--quiet",
                    ]
                ),
                0,
            )

        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(permission_mode(path), 0o600)
        self.assertEqual(permission_mode(path.parent), 0o700)

    def test_since_and_until_boundaries_are_inclusive(self) -> None:
        write_session(
            self.root,
            "codex",
            "boundaries",
            [
                ("2026-08-13T09:59:59Z", "Before", "alpha", "completed"),
                ("2026-08-13T10:00:00Z", "At since", "alpha", "completed"),
                ("2026-08-13T11:00:00Z", "At until", "alpha", "completed"),
                ("2026-08-13T11:00:01Z", "After", "alpha", "completed"),
            ],
        )
        since = dt.datetime(2026, 8, 13, 10, tzinfo=dt.timezone.utc)
        until = dt.datetime(2026, 8, 13, 11, tzinfo=dt.timezone.utc)

        entries = filter_entries(collect_entries(), since=since, until=until)
        report = build_report(entries, since=since, until=until)

        self.assertIn("At since", report)
        self.assertIn("At until", report)
        self.assertNotIn("Before", report)
        self.assertNotIn("After", report)

    def test_cli_bad_window_value_exits_two_with_parse_message(self) -> None:
        errors = io.StringIO()

        with contextlib.redirect_stderr(errors):
            status = main(["report", "--until", "eventually"])

        self.assertEqual(status, 2)
        self.assertIn("invalid --since value 'eventually'", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
