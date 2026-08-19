"""Claude Code hook that supplies worklog checkpoint instructions.

The hook fires on every prompt but writes nothing to the ledger. It hands
Claude the stable session ID plus the rule for recording a checkpoint. The
full rule is only worth spending context on once per session, so later turns
in the same session receive a short reminder instead.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

from .hookstate import decide


def _shell_quote(value: str) -> str:
    """Return a single-quoted shell word without invoking a shell."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_context(session_id: str) -> str:
    """Build the full instruction Claude Code receives for one session."""
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


def build_terse_context(session_id: str) -> str:
    """Build the short reminder for a session that already has the full rule."""
    quoted_session_id = _shell_quote(session_id)
    return (
        "If this turn produced material, verified work, record it before the "
        f"final response with `worklog add --agent claude --session-id "
        f"{quoted_session_id}`. Evidence is required. Skip conversational or "
        "no-op turns."
    )


def build_response(session_id: str, terse: bool = False) -> dict[str, Any]:
    """Build a Claude Code UserPromptSubmit response."""
    context = build_terse_context(session_id) if terse else build_context(session_id)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def _payload_field(payload: object, name: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def main(argv: Sequence[str] | None = None) -> int:
    """Read one hook payload and always return a usable JSON response."""
    del argv
    session_id = "unknown"
    transcript_path: str | None = None
    try:
        payload = json.loads(sys.stdin.read())
        session_id = _payload_field(payload, "session_id") or "unknown"
        transcript_path = _payload_field(payload, "transcript_path")
    except Exception:
        pass

    terse = not decide(session_id, transcript_path)
    print(json.dumps(build_response(session_id, terse=terse)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
