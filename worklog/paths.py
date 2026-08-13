"""Resolve worklog data paths."""

from __future__ import annotations

import os
from pathlib import Path


def _absolute_without_resolving(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.absolute()

    # PWD preserves a caller's logical synced or symlinked path; resolve() would
    # collapse it to the physical target and lose that useful path identity.
    logical_pwd = Path(os.environ.get("PWD", os.getcwd())).expanduser().absolute()
    return (logical_pwd / path).absolute()


def ensure_private_dir(path: Path) -> Path:
    """Create each missing directory level with mode 0700 and return path."""
    missing: list[Path] = []
    current = Path(path)
    while not current.is_dir():
        if current.exists() or current.is_symlink():
            raise NotADirectoryError(f"not a directory: {current}")
        missing.append(current)
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(f"no existing ancestor for directory: {path}")
        current = parent

    for directory in reversed(missing):
        try:
            os.mkdir(directory, mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise
        else:
            os.chmod(directory, 0o700)
    return Path(path)


def ledger_root() -> Path:
    """Return the configured ledger root without creating it."""
    configured = os.environ.get("WORKLOG_DIR")
    if configured:
        return _absolute_without_resolving(configured)

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return _absolute_without_resolving(Path(xdg_data_home) / "worklog")

    return _absolute_without_resolving(Path.home() / ".local" / "share" / "worklog")


def sessions_dir() -> Path:
    """Return the directory containing per-agent session ledgers."""
    return ledger_root() / "sessions"


def reports_dir() -> Path:
    """Return the directory containing generated reports."""
    return ledger_root() / "reports"
