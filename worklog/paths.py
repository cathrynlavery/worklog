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
