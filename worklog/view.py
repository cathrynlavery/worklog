"""Collect, filter, and render session worklog checkpoints."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import ledger_root


CHECKPOINT = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)
SESSION_ID = re.compile(r"^- \*\*Session ID:\*\* `([^`]+)`$", re.MULTILINE)
STATUS = re.compile(r"^- \*\*Status:\*\* (\S+)$", re.MULTILINE)
PROJECT = re.compile(r"^- \*\*Project:\*\* `([^`]+)`$", re.MULTILINE)
RELATIVE_SINCE = re.compile(r"^(\d+)([dh])$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_SECTIONS = ("### Accomplished", "### Evidence", "### Remaining")


@dataclass(frozen=True)
class Entry:
    """One checkpoint from a session ledger."""

    timestamp: str
    agent: str
    project: str
    title: str
    status: str
    path: str
    session_id: str


def _parse_timestamp(value: str) -> dt.datetime:
    if value.endswith("Z"):
        normalized = f"{value[:-1]}+00:00"
    elif re.search(r"[+-]\d{2}:\d{2}$", value):
        normalized = value
    else:
        raise ValueError("timestamp must include a UTC offset")

    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _local_day_start(day: dt.date) -> dt.datetime:
    local_midnight = dt.datetime.combine(day, dt.time.min)
    return local_midnight.astimezone(dt.timezone.utc)


def parse_since(value: str) -> dt.datetime:
    """Parse a viewer --since value into a timezone-aware UTC datetime."""
    normalized = value.strip().lower()
    now = dt.datetime.now(dt.timezone.utc)

    def invalid_value() -> ValueError:
        return ValueError(
            f"invalid --since value {value!r}; use today, yesterday, week, month, "
            "YYYY-MM-DD, Nd, or Nh"
        )

    if normalized in {"week", "month"}:
        days = 7 if normalized == "week" else 30
        return now - dt.timedelta(days=days)

    relative = RELATIVE_SINCE.fullmatch(normalized)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        try:
            delta = (
                dt.timedelta(days=amount)
                if unit == "d"
                else dt.timedelta(hours=amount)
            )
            return now - delta
        except OverflowError as error:
            raise invalid_value() from error

    local_today = dt.datetime.now().astimezone().date()
    if normalized == "today":
        return _local_day_start(local_today)
    if normalized == "yesterday":
        return _local_day_start(local_today - dt.timedelta(days=1))

    if ISO_DATE.fullmatch(normalized) is None:
        raise invalid_value()
    try:
        day = dt.date.fromisoformat(normalized)
    except ValueError as error:
        raise invalid_value() from error
    return _local_day_start(day)


def parse_session_file(path: Path) -> list[Entry]:
    """Parse every complete checkpoint in a session ledger file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []

    checkpoints = list(CHECKPOINT.finditer(text))
    if not checkpoints:
        return []

    session_match = SESSION_ID.search(text, 0, checkpoints[0].start())
    session_id = session_match.group(1) if session_match is not None else path.stem

    entries: list[Entry] = []
    for index, checkpoint in enumerate(checkpoints):
        block_end = (
            checkpoints[index + 1].start()
            if index + 1 < len(checkpoints)
            else len(text)
        )
        block = text[checkpoint.end() : block_end]
        section_positions = [block.find(section) for section in REQUIRED_SECTIONS]
        if -1 in section_positions or section_positions != sorted(section_positions):
            continue
        if not block.rstrip().endswith("---"):
            continue

        metadata = block[: section_positions[0]]
        status_match = STATUS.search(metadata)
        project_match = PROJECT.search(metadata)
        if status_match is None or project_match is None:
            continue

        timestamp = checkpoint.group(1)
        title = checkpoint.group(2).strip()
        if not title:
            continue
        try:
            _parse_timestamp(timestamp)
        except ValueError:
            continue

        entries.append(
            Entry(
                timestamp=timestamp,
                agent=path.parent.name,
                project=project_match.group(1),
                title=title,
                status=status_match.group(1),
                path=str(path),
                session_id=session_id,
            )
        )
    return entries


def collect_entries(root: Path | None = None) -> list[Entry]:
    """Collect all local checkpoints, sorted newest first."""
    sessions = (root if root is not None else ledger_root()) / "sessions"
    try:
        paths = sorted(sessions.glob("*/*.md"))
    except OSError:
        return []

    entries = [entry for path in paths for entry in parse_session_file(path)]
    entries.sort(key=lambda entry: _parse_timestamp(entry.timestamp), reverse=True)
    return entries


def filter_entries(
    entries: Iterable[Entry],
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    agent: str | None = None,
    project: str | None = None,
) -> list[Entry]:
    """Return entries matching the requested time and identity filters."""
    if since is not None and since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    if until is not None and until.tzinfo is None:
        raise ValueError("until must be timezone-aware")

    since_utc = since.astimezone(dt.timezone.utc) if since is not None else None
    until_utc = until.astimezone(dt.timezone.utc) if until is not None else None
    selected: list[Entry] = []
    for entry in entries:
        timestamp = _parse_timestamp(entry.timestamp)
        if since_utc is not None and timestamp < since_utc:
            continue
        if until_utc is not None and timestamp > until_utc:
            continue
        if agent is not None and entry.agent != agent:
            continue
        if project is not None and entry.project != project:
            continue
        selected.append(entry)
    return selected


def render(entries: Iterable[Entry], *, show_path: bool = True) -> str:
    """Render entries in the human-readable recent-checkpoint table."""
    lines: list[str] = []
    for entry in entries:
        lines.append(
            f"{entry.timestamp}  {entry.agent:<7}  {entry.project:<24}  {entry.title}"
        )
        if show_path:
            lines.append(f"  {entry.path}")
    return "\n".join(lines)
