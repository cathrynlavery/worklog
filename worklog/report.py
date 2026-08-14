"""Build and persist plain Markdown worklog reports."""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .paths import ensure_private_dir, reports_dir
from .view import Entry, _parse_timestamp


CHECKPOINT_HEADER = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)
SECTION_HEADER = re.compile(r"^(?:### .+|---)\s*$", re.MULTILINE)
UNCHECKED_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
EMOJI = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F000-\U0001FAFF"
    "\u2600-\u27BF"
    "\u200D\u20E3\uFE0F"
    "]"
)


def _plain_text(value: str) -> str:
    """Remove terminal colour and pictographs unsuitable for email reports."""
    return EMOJI.sub("", ANSI_ESCAPE.sub("", value)).strip()


def _display_day(value: dt.datetime) -> dt.date:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("report boundaries must be timezone-aware")
    return value.astimezone().date()


def _period(since: dt.datetime, until: dt.datetime | None) -> str:
    start = _display_day(since)
    end = (
        _display_day(until)
        if until is not None
        else dt.datetime.now().astimezone().date()
    )
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} to {end.isoformat()}"


def _count_label(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _checkpoint_block(text: str, entry: Entry) -> str | None:
    checkpoints = list(CHECKPOINT_HEADER.finditer(text))
    for index, checkpoint in enumerate(checkpoints):
        if checkpoint.group(1) != entry.timestamp:
            continue
        if checkpoint.group(2).strip() != entry.title:
            continue
        end = (
            checkpoints[index + 1].start()
            if index + 1 < len(checkpoints)
            else len(text)
        )
        return text[checkpoint.end() : end]
    return None


def _remaining_items(entry: Entry, cache: dict[str, str | None]) -> list[str]:
    if entry.path not in cache:
        try:
            cache[entry.path] = Path(entry.path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            cache[entry.path] = None

    text = cache[entry.path]
    if text is None:
        return []
    block = _checkpoint_block(text, entry)
    if block is None:
        return []

    marker = re.search(r"^### Remaining\s*$", block, re.MULTILINE)
    if marker is None:
        return []
    following = block[marker.end() :]
    next_section = SECTION_HEADER.search(following)
    section = (
        following[: next_section.start()] if next_section is not None else following
    )
    return [_plain_text(match.group(1)) for match in UNCHECKED_ITEM.finditer(section)]


def _entry_time(entry: Entry) -> str:
    timestamp = entry.timestamp
    if timestamp.endswith("Z"):
        timestamp = f"{timestamp[:-1]}+00:00"
    parsed = dt.datetime.fromisoformat(timestamp)
    return parsed.strftime("%H:%M")


def build_report(
    entries: Iterable[Entry],
    *,
    since: dt.datetime,
    until: dt.datetime | None = None,
    title: str | None = None,
) -> str:
    """Return a plain Markdown report for an already-filtered entry window."""
    period = _period(since, until)
    heading = _plain_text(title) if title is not None else f"Worklog — {period}"
    selected = list(entries)
    selected.sort(key=lambda entry: _parse_timestamp(entry.timestamp), reverse=True)

    projects = {entry.project for entry in selected}
    agents = {entry.agent for entry in selected}
    summary = (
        f"{_count_label(len(selected), 'checkpoint')} across "
        f"{_count_label(len(projects), 'project')} and "
        f"{_count_label(len(agents), 'agent')}."
    )
    if not selected:
        summary += " Nothing was recorded in this window."

    lines = [f"# {heading}", "", summary]
    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entry in selected:
        grouped[entry.project].append(entry)

    ordered_projects = sorted(
        grouped.items(),
        key=lambda item: (
            -len(item[1]),
            -_parse_timestamp(item[1][0].timestamp).timestamp(),
            item[0].casefold(),
        ),
    )
    for project, project_entries in ordered_projects:
        lines.extend(("", f"## {_plain_text(project)}", ""))
        for entry in project_entries:
            lines.append(
                f"- {_entry_time(entry)} — {_plain_text(entry.title)} "
                f"({_plain_text(entry.agent)})"
            )

    cache: dict[str, str | None] = {}
    remaining: list[tuple[str, str]] = []
    for entry in selected:
        remaining.extend(
            (entry.project, item) for item in _remaining_items(entry, cache) if item
        )

    lines.extend(("", "## Still open", ""))
    if remaining:
        lines.extend(
            f"- [ ] {_plain_text(item)} ({_plain_text(project)})"
            for project, item in remaining
        )
    else:
        lines.append("No remaining items were recorded.")
    return "\n".join(lines) + "\n"


def write_report(text: str, *, day: dt.date) -> Path:
    """Overwrite one dated report with private filesystem permissions."""
    directory = ensure_private_dir(reports_dir())
    path = directory / f"{day.isoformat()}.md"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".worklog-report-", dir=directory)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as report_file:
            report_file.write(text)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return path
