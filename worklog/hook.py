"""Claude Code hook that supplies worklog checkpoint instructions."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any


def _shell_quote(value: str) -> str:
    """Return a single-quoted shell word without invoking a shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_context(session_id: str) -> str:
    """Build the instruction Claude Code receives for one session."""
    quoted_session_id = _shell_quote(session_id)
    return (
        f"This is session {session_id}. If THIS turn produced material, verified "
        "work, record it before the final response with `worklog add --agent "
        f"claude --session-id {quoted_session_id} --title '...' --done '...' "
        "--evidence '...'` and optional `--remaining '...'`. Evidence is "
        "required and must be a commit SHA, test result, URL, or artifact "
        "path. Use `--allow-no-evidence` only in the rare case where verified "
        "work genuinely has nothing citable. Do not log conversational or "
        "no-op turns, secrets, credentials, PHI, raw transcripts, or "
        "unverified claims."
    )


def build_response(session_id: str) -> dict[str, Any]:
    """Build a Claude Code UserPromptSubmit response."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": build_context(session_id),
        }
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Read one hook payload and always return a usable JSON response."""
    del argv
    session_id = "unknown"
    try:
        payload = json.loads(sys.stdin.read())
        if isinstance(payload, dict):
            candidate = payload.get("session_id")
            if isinstance(candidate, str) and candidate:
                session_id = candidate
    except Exception:
        pass

    print(json.dumps(build_response(session_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
