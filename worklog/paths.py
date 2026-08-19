"""Resolve worklog data paths."""

from __future__ import annotations

import os
import stat
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


def state_root() -> Path:
    """Return the root for ephemeral hook state without creating it.

    Hook bookkeeping is regenerable and deliberately kept out of the ledger so
    that losing it costs one verbose instruction, never a checkpoint.
    """
    configured = os.environ.get("WORKLOG_STATE_DIR")
    if configured:
        return _absolute_without_resolving(configured)

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return _absolute_without_resolving(Path(xdg_state_home) / "worklog")

    return _absolute_without_resolving(Path.home() / ".local" / "state" / "worklog")


def hook_state_dir() -> Path:
    """Return the directory holding per-session prompt-hook state."""
    return state_root() / "hook-sessions"


def enforce_private_dir(path: Path) -> Path:
    """Create path and tighten it to 0700 even when it already existed.

    ensure_private_dir only sets the mode on levels it creates, which leaves a
    pre-existing directory readable by group or other. Hook state is entirely
    regenerable and owned by worklog, so tightening it is always safe: there is
    no user-arranged content here to disturb.
    """
    ensure_private_dir(path)
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        os.chmod(path, 0o700)
    return Path(path)
