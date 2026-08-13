"""Redact credentials and private keys from worklog text."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _built_in_redact(value: str) -> str:
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b",
        "[REDACTED TOKEN]",
        value,
    )
    value = re.sub(
        r"(?i)\b(secret|token|password|api[_ -]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        value,
    )
    return value


def redact(value: str) -> str:
    """Return redacted text, falling back safely if an override fails."""
    configured = os.environ.get("WORKLOG_REDACTOR")
    if configured:
        try:
            redactor = Path(configured).expanduser()
            if redactor.is_file() and os.access(redactor, os.X_OK):
                result = subprocess.run(
                    [str(redactor)],
                    input=value,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout:
                    return result.stdout.rstrip("\n")
        except Exception:
            pass
    return _built_in_redact(value)
