#!/usr/bin/env python3
"""Generate the sanitized HTML digest used for README screenshots."""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from worklog.digest import build_digest, digest_window
from worklog.view import collect_entries, filter_entries


CHECKPOINTS = {
    "codex": [
        (
            "2026-08-16T17:42:00Z",
            "Closed the inventory reservation race",
            "checkout-api",
            "completed",
            "Made reservation writes idempotent under concurrent retries.",
            "184 tests passed; commit 8c4a7f2",
            "Watch production retry volume after Monday's deploy.",
        ),
        (
            "2026-08-16T15:18:00Z",
            "Cut cold-start latency by 38%",
            "checkout-api",
            "completed",
            "Moved schema loading out of the request path and warmed the cache.",
            "Benchmark: p95 812ms → 503ms across 500 cold starts",
            None,
        ),
    ],
    "claude": [
        (
            "2026-08-16T18:31:00Z",
            "Shipped accessible checkout states",
            "design-system",
            "completed",
            "Added keyboard, focus, error, and reduced-motion states to checkout.",
            "axe: 0 violations; screenshots in artifacts/checkout-a11y",
            "Verify VoiceOver flow on a physical iPhone.",
        ),
        (
            "2026-08-16T13:05:00Z",
            "Published the v2 migration guide",
            "design-system",
            "partial",
            "Documented every breaking token rename with before/after examples.",
            "docs/migration-v2.md; link check passed",
            "Add the React Native example.",
        ),
    ],
    "hermes": [
        (
            "2026-08-16T19:04:00Z",
            "Verified the release candidate on macOS and Linux",
            "release-ops",
            "completed",
            "Ran install, upgrade, rollback, and clean-machine smoke tests.",
            "CI run 31767359967; release checklist 14/14",
            None,
        ),
        (
            "2026-08-16T11:26:00Z",
            "Added failed-payment alerting",
            "release-ops",
            "partial",
            "Routed failed payment events into the on-call digest with deduplication.",
            "Fixture replay: 12 events → 3 actionable alerts",
            "Tune the retry threshold after one week of data.",
        ),
    ],
}


def write_fixture(root: Path, agent: str, checkpoints: list[tuple[str, ...]]) -> None:
    directory = root / "sessions" / agent
    directory.mkdir(parents=True, mode=0o700)
    blocks = []
    for timestamp, title, project, status, done, evidence, remaining in checkpoints:
        remaining_line = (
            f"- [ ] {remaining}" if remaining is not None else "- None recorded."
        )
        blocks.append(
            f"## {timestamp} — {title}\n\n"
            f"- **Status:** {status}\n"
            f"- **Project:** `{project}`\n"
            "- **Working directory:** `/Users/example/Developer/project`\n"
            "- **Branch:** `main`\n"
            "- **Commit:** `8c4a7f2`\n"
            "- **Working tree:** clean\n"
            "- **Machine:** `studio.local`\n\n"
            "### Accomplished\n\n"
            f"- [x] {done}\n\n"
            "### Evidence\n\n"
            f"- {evidence}\n\n"
            "### Remaining\n\n"
            f"{remaining_line}\n\n"
            "---\n\n"
        )
    session_id = f"preview-{agent}"
    content = (
        "# Session accomplishment ledger\n\n"
        f"- **Session ID:** `{session_id}`\n"
        f"- **Agent:** `{agent}`\n"
        f"- **Created:** {checkpoints[-1][0]}\n\n"
        + "".join(blocks)
    )
    path = directory / f"{session_id}.md"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def main() -> None:
    destination = PROJECT_ROOT / "docs" / "digest-preview.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        ledger = Path(temporary) / "ledger"
        for agent, checkpoints in CHECKPOINTS.items():
            write_fixture(ledger, agent, checkpoints)
        day = dt.date(2026, 8, 16)
        since, until = digest_window("daily", day=day)
        entries = filter_entries(
            collect_entries(ledger), since=since, until=until
        )
        digest = build_digest(
            entries,
            period="daily",
            since=since,
            until=until,
            generated_at=dt.datetime(2026, 8, 16, 21, 5).astimezone(),
        )
        destination.write_text(digest, encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
