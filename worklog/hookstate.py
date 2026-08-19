"""Per-session bookkeeping that keeps the prompt hook from repeating itself.

The hook runs on every prompt, but the full checkpoint instruction only needs
to be in context once. This module remembers what a session has already been
told so later turns can carry a short reminder instead of the whole rule.

Every failure here is answered with the verbose instruction. A lost, corrupt,
or unwritable state file must never cost a checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .paths import ensure_private_dir, hook_state_dir


# Re-send the full instruction periodically so a long session cannot drift far
# from the rule even when no compaction is detected.
REASSERT_EVERY_TURNS = 25

# Prune abandoned session files rather than accumulating one per conversation.
STALE_STATE_AFTER_SECONDS = 30 * 24 * 60 * 60

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _state_file(session_id: str) -> Path:
    """Return the state path for session_id, keeping the name filesystem-safe."""
    safe = _UNSAFE_NAME.sub("-", session_id)[:64]
    # Session IDs reach us from an external agent, so the digest guarantees a
    # unique file even when sanitising collapses two different IDs.
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return hook_state_dir() / f"{safe}.{digest}.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    """Replace path atomically so a concurrent turn never reads a torn file."""
    ensure_private_dir(path.parent)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)


def _transcript_size(transcript_path: str | None) -> int | None:
    if not transcript_path:
        return None
    try:
        return Path(transcript_path).stat().st_size
    except OSError:
        return None


def _prune_stale(directory: Path, now: float) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if now - entry.stat().st_mtime > STALE_STATE_AFTER_SECONDS:
                entry.unlink(missing_ok=True)
        except OSError:
            continue


def needs_full_instruction(
    session_id: str,
    transcript_path: str | None = None,
    now: float | None = None,
) -> bool:
    """Record one turn for session_id and report whether it needs the full rule.

    The full instruction is sent on the first turn of a session, again whenever
    the transcript shrinks (the signal that compaction dropped it from context),
    and every REASSERT_EVERY_TURNS turns as a backstop.
    """
    if not session_id or session_id == "unknown":
        # Without a stable ID, turns cannot be attributed to one conversation.
        return True

    moment = time.time() if now is None else now
    path = _state_file(session_id)
    state = _read_state(path)

    previous_turns = state.get("turns")
    turns = (previous_turns if isinstance(previous_turns, int) else 0) + 1

    previous_size = state.get("transcript_size")
    current_size = _transcript_size(transcript_path)
    compacted = (
        isinstance(previous_size, int)
        and current_size is not None
        and current_size < previous_size
    )

    full = turns == 1 or compacted or turns % REASSERT_EVERY_TURNS == 1

    updated: dict[str, Any] = {
        "turns": 1 if compacted else turns,
        "updated": moment,
        "saw_transcript_path": bool(transcript_path),
    }
    if current_size is not None:
        updated["transcript_size"] = current_size

    _write_state(path, updated)
    _prune_stale(path.parent, moment)
    return full


def decide(
    session_id: str,
    transcript_path: str | None = None,
    now: float | None = None,
) -> bool:
    """Return whether this turn needs the full instruction, failing open."""
    try:
        return needs_full_instruction(session_id, transcript_path, now)
    except Exception:
        # An unwritable or hostile state directory degrades to today's
        # behaviour: verbose, correct, and never a broken prompt.
        return True
