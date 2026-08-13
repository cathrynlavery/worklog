"""Import an existing accomplishment ledger without rewriting its contents."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import ensure_private_dir, ledger_root
from .record import safe_component
from .view import parse_session_file


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


def import_ledger(
    source: Path,
    *,
    dest: Path | None = None,
    dry_run: bool = False,
    on_conflict: str = "skip",
) -> ImportResult:
    """Copy valid session files from an existing ledger into a worklog ledger."""
    if on_conflict not in {"skip", "replace", "rename"}:
        raise ValueError("on_conflict must be 'skip', 'replace', or 'rename'")

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
        if _is_occupied(destination, reserved):
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
