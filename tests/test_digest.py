"""Tests for self-contained daily and weekly HTML digests."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import unittest

from worklog.cli import main
from worklog.digest import build_digest, digest_window, write_digest
from worklog.paths import reports_dir
from worklog.view import collect_entries, filter_entries

from tests.support import TempLedger, permission_mode, write_session


class DigestTests(TempLedger):
    def test_daily_digest_is_self_contained_and_escapes_checkpoint_content(self) -> None:
        session = write_session(
            self.root,
            "codex",
            "digest-safe",
            [
                (
                    "2026-08-16T12:00:00Z",
                    "Ship <script>alert(1)</script>",
                    "alpha & beta",
                    "completed",
                )
            ],
        )
        session.write_text(
            session.read_text(encoding="utf-8")
            .replace("Synthetic accomplishment.", "A real <strong>outcome</strong>.")
            .replace("Synthetic evidence.", "https://example.com/proof")
            .replace("test-machine", "studio <one> &"),
            encoding="utf-8",
        )
        since, until = digest_window("daily", day=dt.date(2026, 8, 16))
        entries = filter_entries(collect_entries(), since=since, until=until)

        digest = build_digest(
            entries,
            period="daily",
            since=since,
            until=until,
            generated_at=dt.datetime(2026, 8, 16, 21, tzinfo=dt.timezone.utc),
        )

        self.assertTrue(digest.startswith("<!doctype html>"))
        self.assertNotIn("<script>alert(1)</script>", digest)
        self.assertIn("<script>", digest)
        self.assertNotIn("<script src=", digest)
        self.assertIn("Ship &lt;script&gt;alert(1)&lt;/script&gt;", digest)
        self.assertIn("alpha &amp; beta", digest)
        self.assertIn("A real &lt;strong&gt;outcome&lt;/strong&gt;.", digest)
        self.assertIn('href="https://example.com/proof"', digest)
        self.assertIn("1</strong><span>checkpoints", digest)
        self.assertIn("Sunday, August 16, 2026", digest)
        self.assertIn('id="view-picker"', digest)
        self.assertIn('id="overview" data-digest-view', digest)
        self.assertIn('id="project-0" data-digest-view hidden', digest)
        self.assertIn('id="contributor-0" data-digest-view hidden', digest)
        self.assertIn('id="computer-0" data-digest-view hidden', digest)
        self.assertIn('<optgroup label="Projects">', digest)
        self.assertIn('<optgroup label="Contributors">', digest)
        self.assertIn('<optgroup label="Computers">', digest)
        self.assertIn("studio &lt;one&gt; &amp; (1)", digest)
        self.assertIn("--paper:#f5f4ed", digest)
        self.assertIn("--accent:#f7591f", digest)
        self.assertIn('--font-serif:"Instrument Serif"', digest)
        self.assertIn("Cathryn Lavery · local work ledger", digest)
        self.assertIn("What <em>actually got done.</em>", digest)
        self.assertIn("<span>contributors</span>", digest)
        self.assertIn("<span>computers</span>", digest)

    def test_view_selector_indexes_dimensions_and_limits_overview_cards(self) -> None:
        checkpoints = [
            (
                f"2026-08-16T{23 - index:02d}:00:00Z",
                f"Finished outcome {index}",
                f"project-{index:02d}",
                "completed",
            )
            for index in range(14)
        ]
        write_session(self.root, "codex", "many-projects", checkpoints)
        since, until = digest_window("daily", day=dt.date(2026, 8, 16))
        entries = filter_entries(collect_entries(), since=since, until=until)

        digest = build_digest(entries, period="daily", since=since, until=until)

        self.assertEqual(digest.count('<option value="project-'), 14)
        self.assertEqual(digest.count('<option value="contributor-'), 1)
        self.assertEqual(digest.count('<option value="computer-'), 1)
        self.assertEqual(digest.count('class="project-card"'), 12)
        self.assertEqual(digest.count('class="digest-view" id="project-'), 14)
        self.assertEqual(digest.count('class="digest-view" id="contributor-'), 1)
        self.assertEqual(digest.count('class="digest-view" id="computer-'), 1)
        self.assertIn("+2 more projects", digest)
        self.assertIn('data-select-view="project-0"', digest)
        self.assertIn('data-select-view="overview"', digest)

    def test_weekly_window_starts_monday_and_ends_sunday(self) -> None:
        since, until = digest_window("weekly", day=dt.date(2026, 8, 16))

        self.assertEqual(since.astimezone().date(), dt.date(2026, 8, 10))
        self.assertEqual(until.astimezone().date(), dt.date(2026, 8, 16))
        self.assertEqual(until.time(), dt.time(23, 59, 59, 999999))

    def test_empty_digest_has_valid_summary_and_open_state(self) -> None:
        since, until = digest_window("weekly", day=dt.date(2026, 8, 16))

        digest = build_digest(
            [], period="weekly", since=since, until=until
        )

        self.assertIn("Weekly worklog", digest)
        self.assertIn("0</strong><span>checkpoints", digest)
        self.assertIn("No checkpoints were recorded in this window.", digest)
        self.assertIn("No remaining items were recorded.", digest)

    def test_write_digest_is_private_and_uses_stable_names(self) -> None:
        daily = write_digest("daily", period="daily", day=dt.date(2026, 8, 16))
        weekly = write_digest("weekly", period="weekly", day=dt.date(2026, 8, 16))

        self.assertEqual(daily, reports_dir() / "digests" / "daily-2026-08-16.html")
        self.assertEqual(weekly, reports_dir() / "digests" / "weekly-2026-W33.html")
        self.assertEqual(daily.read_text(encoding="utf-8"), "daily")
        self.assertEqual(weekly.read_text(encoding="utf-8"), "weekly")
        self.assertEqual(permission_mode(daily.parent), 0o700)
        self.assertEqual(permission_mode(daily), 0o600)
        self.assertEqual(permission_mode(weekly), 0o600)

    def test_cli_period_all_writes_both_digests_quietly(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = main(
                [
                    "digest",
                    "--period",
                    "all",
                    "--date",
                    "2026-08-16",
                    "--write",
                    "--quiet",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(
            (reports_dir() / "digests" / "daily-2026-08-16.html").is_file()
        )
        self.assertTrue(
            (reports_dir() / "digests" / "weekly-2026-W33.html").is_file()
        )

    def test_cli_all_requires_write_and_rejects_bad_date(self) -> None:
        errors = io.StringIO()

        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(["digest", "--period", "all"]), 2)
            self.assertEqual(main(["digest", "--date", "soon"]), 2)

        self.assertIn("--period all requires --write", errors.getvalue())
        self.assertIn("use YYYY-MM-DD", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
