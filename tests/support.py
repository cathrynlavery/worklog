"""Shared, hermetic fixtures for the worklog test suite."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CONTROLLED_ENVIRONMENT = (
    "WORKLOG_DIR",
    "WORKLOG_STATE_DIR",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "WORKLOG_REDACTOR",
    "HOME",
    "CODEX_THREAD_ID",
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_ENTRYPOINT",
)


class TempLedger(unittest.TestCase):
    """Base test case with a private ledger and fully isolated environment."""

    def setUp(self) -> None:
        super().setUp()
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.sandbox = Path(self._temporary_directory.name)
        self.root = self.sandbox / "ledger"
        self.home = self.sandbox / "home"
        self.xdg_data_home = self.sandbox / "xdg"
        self.state_root = self.sandbox / "state"
        self.home.mkdir(mode=0o700)

        environment = {
            "HOME": str(self.home),
            "PATH": os.defpath,
            "PWD": str(self.sandbox),
            "WORKLOG_DIR": str(self.root),
            "WORKLOG_STATE_DIR": str(self.state_root),
            "XDG_DATA_HOME": str(self.xdg_data_home),
        }
        self._environment = mock.patch.dict(os.environ, environment, clear=True)
        self._environment.start()
        self.addCleanup(self._environment.stop)

        # These names are deliberately absent unless a test opts into one.
        for name in CONTROLLED_ENVIRONMENT:
            if name not in environment:
                self.assertNotIn(name, os.environ)


def private_mkdir(path: Path) -> Path:
    """Create a synthetic fixture directory with deterministic private modes."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in missing:
        os.chmod(directory, 0o700)
    return path


def write_session(
    root: Path,
    agent: str,
    session_id: str,
    checkpoints: list[tuple[str, str, str, str]],
) -> Path:
    """Write checkpoints in exactly the format emitted by record()."""
    directory = private_mkdir(root / "sessions" / agent)
    created = checkpoints[0][0] if checkpoints else "2026-01-01T00:00:00Z"
    header = (
        "# Session accomplishment ledger\n\n"
        f"- **Session ID:** `{session_id}`\n"
        f"- **Agent:** `{agent}`\n"
        f"- **Created:** {created}\n\n"
    )
    blocks: list[str] = []
    for timestamp, title, project, checkpoint_status in checkpoints:
        blocks.append(
            f"## {timestamp} — {title}\n\n"
            f"- **Status:** {checkpoint_status}\n"
            f"- **Project:** `{project}`\n"
            "- **Working directory:** `/synthetic/project`\n"
            "- **Branch:** `main`\n"
            "- **Commit:** `abc1234`\n"
            "- **Working tree:** clean\n"
            "- **Machine:** `test-machine`\n\n"
            "### Accomplished\n\n"
            "- [x] Synthetic accomplishment.\n\n"
            "### Evidence\n\n"
            "- Synthetic evidence.\n\n"
            "### Remaining\n\n"
            "- None recorded.\n\n"
            "---\n\n"
        )

    path = directory / f"{session_id}.md"
    path.write_text(header + "".join(blocks), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def permission_mode(path: Path) -> int:
    """Return only the portable permission bits for path."""
    return stat.S_IMODE(path.stat().st_mode)
