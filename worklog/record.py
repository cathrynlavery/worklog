"""Append a redacted, evidence-based checkpoint to a per-session ledger."""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
import subprocess
import uuid
from pathlib import Path
from typing import Literal, Sequence

from .paths import ensure_private_dir, sessions_dir
from .redact import redact

MAX_ITEM_LENGTH = 1_000


def run(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def clean_item(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("accomplishment entries cannot be blank")
    if len(normalized) > MAX_ITEM_LENGTH:
        raise ValueError(
            f"entry is {len(normalized)} characters; keep it under {MAX_ITEM_LENGTH}"
        )
    return redact(normalized)


def safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return (cleaned or fallback)[:120]


def git_metadata(cwd: Path) -> dict[str, str]:
    root_value = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if not root_value:
        return {
            "project": cwd.name or str(cwd),
            "root": str(cwd),
            "branch": "not a Git repository",
            "commit": "n/a",
            "working_tree": "n/a",
        }

    root = Path(root_value)
    branch = run(["git", "branch", "--show-current"], cwd=root) or "detached HEAD"
    commit = run(["git", "rev-parse", "--short", "HEAD"], cwd=root) or "unknown"
    status = run(["git", "status", "--porcelain"], cwd=root)
    if status is None:
        working_tree = "unknown"
    elif not status:
        working_tree = "clean"
    else:
        working_tree = f"{len(status.splitlines())} changed path(s)"
    return {
        "project": root.name,
        "root": str(root),
        "branch": branch,
        "commit": commit,
        "working_tree": working_tree,
    }


def format_list(values: Sequence[str], checked: bool | None = None) -> str:
    if not values:
        return "- None recorded."
    prefix = "- "
    if checked is True:
        prefix = "- [x] "
    elif checked is False:
        prefix = "- [ ] "
    return "\n".join(f"{prefix}{clean_item(value)}" for value in values)


def _inferred_agent() -> str:
    if os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") or os.environ.get(
        "CLAUDE_SESSION_ID"
    ):
        return "claude"
    return "agent"


def machine_name() -> str:
    """Return a stable, human-readable name for the computer."""
    override = os.environ.get("WORKLOG_MACHINE", "").strip()
    if override:
        return override
    if platform.system() == "Darwin":
        computer_name = run(["/usr/sbin/scutil", "--get", "ComputerName"])
        if computer_name:
            return computer_name
    return platform.node()


def record(
    *,
    title: str,
    done: Sequence[str],
    evidence: Sequence[str] = (),
    allow_no_evidence: bool = False,
    remaining: Sequence[str] = (),
    agent: str | None = None,
    session_id: str | None = None,
    cwd: str | Path | None = None,
    project: str | None = None,
    status: Literal["completed", "partial"] | None = None,
) -> Path:
    """Append a checkpoint and return its per-session ledger path."""
    if not done:
        raise ValueError("at least one done item is required")
    if not evidence and not allow_no_evidence:
        raise ValueError(
            "evidence is required: provide a commit SHA, test result, URL, "
            "or artifact path"
        )
    if status not in (None, "completed", "partial"):
        raise ValueError("status must be 'completed' or 'partial'")

    cwd_path = Path(cwd if cwd is not None else os.getcwd()).expanduser().resolve()
    if not cwd_path.exists():
        raise ValueError(f"cwd does not exist: {cwd_path}")

    agent_value = agent if agent is not None else _inferred_agent()
    agent_key = safe_component(agent_value.lower(), "agent")
    session_id_value = (
        session_id
        or os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or f"manual-{uuid.uuid4().hex}"
    )
    session_key = safe_component(
        session_id_value, f"manual-{uuid.uuid4().hex}"
    )
    metadata = git_metadata(cwd_path)
    if project:
        metadata["project"] = clean_item(project)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    timestamp = now.isoformat().replace("+00:00", "Z")
    # Remaining work intentionally implies partial unless --status overrides it.
    checkpoint_status = status or ("partial" if remaining else "completed")
    clean_title = clean_item(title)

    session_path = ensure_private_dir(sessions_dir() / agent_key)
    path = session_path / f"{session_key}.md"

    header = (
        "# Session accomplishment ledger\n\n"
        f"- **Session ID:** `{clean_item(session_id_value)}`\n"
        f"- **Agent:** `{agent_key}`\n"
        f"- **Created:** {timestamp}\n\n"
    )
    checkpoint = (
        f"## {timestamp} — {clean_title}\n\n"
        f"- **Status:** {checkpoint_status}\n"
        f"- **Project:** `{metadata['project']}`\n"
        f"- **Working directory:** `{redact(metadata['root'])}`\n"
        f"- **Branch:** `{clean_item(metadata['branch'])}`\n"
        f"- **Commit:** `{clean_item(metadata['commit'])}`\n"
        f"- **Working tree:** {clean_item(metadata['working_tree'])}\n"
        f"- **Machine:** `{clean_item(machine_name())}`\n\n"
        "### Accomplished\n\n"
        f"{format_list(done, checked=True)}\n\n"
        "### Evidence\n\n"
        f"{format_list(evidence)}\n\n"
        "### Remaining\n\n"
        f"{format_list(remaining, checked=False)}\n\n"
        "---\n\n"
    )

    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND)
        content = checkpoint
    else:
        content = header + checkpoint

    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)

    return path
