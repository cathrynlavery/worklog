#!/usr/bin/env python3
"""Generate a public-safe digest from real Cathryn projects for README screenshots."""

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
    "cathryn": [
        (
            "2026-08-16T20:15:00Z",
            "Set the public-launch direction for Worklog",
            "worklog",
            "partial",
            "Defined the project-first digest, Little Might visual language, and human-inclusive positioning.",
            "Direction reviewed in the live local digest preview.",
            "Review the final branch before publishing.",
        ),
    ],
    "codex": [
        (
            "2026-08-16T19:50:44Z",
            "Aligned Worklog digests with Little Might branding",
            "worklog",
            "completed",
            "Applied the warm-paper palette, serif-led hierarchy, restrained coral accents, and editorial project rows.",
            "Local commit 92dbcaf; 94 tests passed; desktop and mobile previews verified.",
            None,
        ),
        (
            "2026-08-16T19:45:50Z",
            "Redesigned Worklog HTML digests for project navigation",
            "worklog",
            "completed",
            "Added a bounded project overview, project picker, focused timelines, and project-specific open work.",
            "Local commit da5aabd; real daily and weekly digests generated with private permissions.",
            None,
        ),
    ],
    "claude": [
        (
            "2026-08-12T20:14:55Z",
            "Figma export tooling slice shipped via codex-build (PR #39)",
            "diagram-design",
            "partial",
            "Shipped the first Figma export tooling slice through the contributor workflow.",
            "Public pull request #39 opened with current-head checks.",
            "Merge after review comments are resolved and checks pass.",
        ),
        (
            "2026-08-12T20:01:13Z",
            "Fixed standalone SVG XML validity",
            "diagram-design",
            "partial",
            "Preserved valid standalone SVG output across export paths.",
            "Targeted SVG fixtures and XML parsing checks passed.",
            "Complete the remaining export compatibility sweep.",
        ),
    ],
    "hermes": [
        (
            "2026-08-12T01:06:57Z",
            "Improved LittleMight 1Password agent-access article and created short-form video packet",
            "little-might",
            "completed",
            "Tightened the operator angle and turned the article into a short-form video packet.",
            "Editorial revision and short-form packet completed in the Little Might workspace.",
            None,
        ),
        (
            "2026-08-11T21:51:22Z",
            "Drafted LittleMight post on 1Password access for AI agents",
            "little-might",
            "completed",
            "Drafted a practical article on giving AI agents scoped credential access.",
            "Draft completed in the Little Might editorial workspace.",
            None,
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
        since, until = digest_window("weekly", day=day)
        entries = filter_entries(
            collect_entries(ledger), since=since, until=until
        )
        digest = build_digest(
            entries,
            period="weekly",
            since=since,
            until=until,
            generated_at=dt.datetime(2026, 8, 16, 21, 5).astimezone(),
        )
        destination.write_text(digest, encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
