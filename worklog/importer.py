"""Import an existing accomplishment ledger without rewriting its contents."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import ensure_private_dir, ledger_root
from .record import safe_component
from .view import CHECKPOINT, Entry, parse_session_file


@dataclass
class ImportResult:
    """Summary of one ledger import."""

    imported_files: int
    imported_checkpoints: int
    skipped_existing: int
    skipped_unparsable: int
    errors: list[str]
    dry_run: bool


def _source_sessions_dir(source: Path) -> Path:
    source_path = source.expanduser().absolute()
    if not source_path.exists():
        raise ValueError(f"import source does not exist: {source_path}")
    if not source_path.is_dir():
        raise ValueError(f"import source is not a directory: {source_path}")

    nested_sessions = source_path / "sessions"
    if nested_sessions.is_dir():
        return nested_sessions
    if source_path.name == "sessions":
        return source_path
    raise ValueError(
        "import source must be a ledger root containing sessions/ or a "
        f"sessions/ directory: {source_path}"
    )


def _is_occupied(path: Path, reserved: set[Path]) -> bool:
    return path in reserved or path.exists() or path.is_symlink()


def _available_destination(base: Path, reserved: set[Path]) -> Path:
    if not _is_occupied(base, reserved):
        return base

    number = 1
    while True:
        candidate = base.with_name(f"{base.stem}-imported-{number}.md")
        if not _is_occupied(candidate, reserved):
            return candidate
        number += 1


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _write_new(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(content)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def _write_replacement(path: Path, content: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".worklog-import-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(content)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def _entry_key(entry: Entry) -> tuple[str, str]:
    return entry.timestamp, entry.title


def _checkpoint_blocks(text: str, entries: list[Entry]) -> dict[tuple[str, str], str]:
    matches = list(CHECKPOINT.finditer(text))
    parsed_keys = {_entry_key(entry) for entry in entries}
    blocks: dict[tuple[str, str], str] = {}
    for index, match in enumerate(matches):
        key = (match.group(1), match.group(2).strip())
        if key not in parsed_keys:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[key] = text[match.start() : end]
    return blocks


def _merged_session_content(
    source_path: Path,
    destination: Path,
    source_entries: list[Entry],
) -> tuple[bytes | None, int]:
    destination_entries = parse_session_file(destination)
    if not destination_entries:
        raise ValueError("existing destination yielded no checkpoints")
    if source_entries[0].session_id != destination_entries[0].session_id:
        raise ValueError("source and destination session IDs differ")

    source_text = source_path.read_text(encoding="utf-8")
    destination_text = destination.read_text(encoding="utf-8")
    source_blocks = _checkpoint_blocks(source_text, source_entries)
    destination_blocks = _checkpoint_blocks(destination_text, destination_entries)

    for key in source_blocks.keys() & destination_blocks.keys():
        if source_blocks[key].strip() != destination_blocks[key].strip():
            raise ValueError(
                "an existing checkpoint differs from the source "
                f"({key[0]} — {key[1]})"
            )

    missing_keys = [
        _entry_key(entry)
        for entry in source_entries
        if _entry_key(entry) not in destination_blocks
    ]
    if not missing_keys:
        return None, 0

    merged = destination_text
    if not merged.endswith("\n"):
        merged += "\n"
    if not merged.endswith("\n\n"):
        merged += "\n"
    merged += "".join(source_blocks[key] for key in missing_keys)
    if not merged.endswith("\n"):
        merged += "\n"
    return merged.encode("utf-8"), len(missing_keys)


def import_ledger(
    source: Path,
    *,
    dest: Path | None = None,
    dry_run: bool = False,
    on_conflict: str = "skip",
) -> ImportResult:
    """Copy valid session files from an existing ledger into a worklog ledger."""
    if on_conflict not in {"skip", "replace", "rename", "merge"}:
        raise ValueError(
            "on_conflict must be 'skip', 'replace', 'rename', or 'merge'"
        )

    source_sessions = _source_sessions_dir(Path(source))
    destination_root = Path(dest if dest is not None else ledger_root()).expanduser()
    destination_root = destination_root.absolute()
    if destination_root.exists() and not destination_root.is_dir():
        raise ValueError(f"import destination is not a directory: {destination_root}")
    resolved_root = destination_root.resolve(strict=False)

    imported_files = 0
    imported_checkpoints = 0
    skipped_existing = 0
    skipped_unparsable = 0
    errors: list[str] = []
    reserved: set[Path] = set()

    try:
        candidates = sorted(source_sessions.glob("*/*.md"))
    except OSError as error:
        return ImportResult(
            imported_files=0,
            imported_checkpoints=0,
            skipped_existing=0,
            skipped_unparsable=0,
            errors=[f"could not scan {source_sessions}: {error}"],
            dry_run=dry_run,
        )

    for source_path in candidates:
        entries = parse_session_file(source_path)
        if not entries:
            skipped_unparsable += 1
            continue

        agent_key = safe_component(source_path.parent.name, "agent")
        session_key = safe_component(source_path.stem, "session")
        base_destination = (
            destination_root / "sessions" / agent_key / f"{session_key}.md"
        )

        destination = base_destination
        occupied = _is_occupied(destination, reserved)
        if occupied:
            if on_conflict == "skip":
                skipped_existing += 1
                continue
            if on_conflict == "rename":
                destination = _available_destination(base_destination, reserved)

        if not _is_within(destination, resolved_root):
            errors.append(
                f"refusing to import {source_path}: destination escapes "
                f"ledger root ({destination})"
            )
            continue

        if occupied and on_conflict == "merge":
            try:
                content, checkpoint_count = _merged_session_content(
                    source_path,
                    destination,
                    entries,
                )
            except (OSError, UnicodeError, ValueError) as error:
                errors.append(f"could not merge {source_path}: {error}")
                continue
            if content is None:
                skipped_existing += 1
                continue
            if not dry_run:
                try:
                    _write_replacement(destination, content)
                except OSError as error:
                    errors.append(f"could not merge {source_path}: {error}")
                    continue
            reserved.add(destination)
            imported_files += 1
            imported_checkpoints += checkpoint_count
            continue

        if dry_run:
            reserved.add(destination)
            imported_files += 1
            imported_checkpoints += len(entries)
            continue

        try:
            content = source_path.read_bytes()
            ensure_private_dir(destination.parent)
            wrote_file = True
            while True:
                try:
                    if on_conflict == "replace":
                        _write_replacement(destination, content)
                    else:
                        _write_new(destination, content)
                    break
                except FileExistsError:
                    if on_conflict == "skip":
                        skipped_existing += 1
                        wrote_file = False
                        break
                    if on_conflict == "rename":
                        destination = _available_destination(
                            base_destination, reserved
                        )
                        if not _is_within(destination, resolved_root):
                            raise OSError(
                                f"destination escapes ledger root: {destination}"
                            )
                        continue
                    raise
            if not wrote_file:
                continue
        except (OSError, UnicodeError) as error:
            errors.append(f"could not import {source_path}: {error}")
            continue

        reserved.add(destination)
        imported_files += 1
        imported_checkpoints += len(entries)

    return ImportResult(
        imported_files=imported_files,
        imported_checkpoints=imported_checkpoints,
        skipped_existing=skipped_existing,
        skipped_unparsable=skipped_unparsable,
        errors=errors,
        dry_run=dry_run,
    )
