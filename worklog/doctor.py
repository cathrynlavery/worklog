"""Diagnose common worklog installation and configuration problems."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .hook import build_context, build_response, build_terse_context
from .hookstate import REASSERT_EVERY_TURNS
from .paths import ensure_private_dir, hook_state_dir, ledger_root
from .view import collect_entries, parse_session_file


Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    """The result of one diagnostic check."""

    name: str
    status: Status
    message: str
    hint: str | None = None


def _path_text(path: Path) -> str:
    return str(path).replace("\n", "\\n").replace("\r", "\\r")


def _error_text(error: BaseException) -> str:
    try:
        detail = str(error)
    except Exception:
        detail = "error details unavailable"
    return f"{type(error).__name__}: {detail}"


def _safe_check(name: str, check: Callable[[], Check]) -> Check:
    try:
        return check()
    except Exception as error:
        return Check(
            name=name,
            status="warn",
            message=f"Could not complete this check ({_error_text(error)}).",
            hint=(
                "Resolve the reported filesystem or configuration error and "
                "rerun doctor."
            ),
        )


def _check_python_version() -> Check:
    version = sys.version_info
    rendered = f"{version[0]}.{version[1]}.{version[2]}"
    if version < (3, 10):
        return Check(
            name="python version",
            status="fail",
            message=f"Python {rendered} is unsupported; worklog requires Python 3.10+.",
            hint="Run worklog with Python 3.10 or newer.",
        )
    return Check(
        name="python version",
        status="ok",
        message=f"Python {rendered} satisfies the 3.10+ requirement.",
    )


def _ledger_source() -> str:
    if os.environ.get("WORKLOG_DIR"):
        return "WORKLOG_DIR"
    if os.environ.get("XDG_DATA_HOME"):
        return "XDG_DATA_HOME"
    return "default"


def _writability_error(root: Path) -> str | None:
    descriptor: int | None = None
    temporary_name: str | None = None
    problem: BaseException | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".worklog-doctor-", dir=root
        )
    except Exception as error:
        problem = error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as error:
                if problem is None:
                    problem = error
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            except OSError as error:
                if problem is None:
                    problem = error

    return _error_text(problem) if problem is not None else None


def _check_ledger_root() -> Check:
    root = ledger_root()
    path = _path_text(root)
    source = _ledger_source()

    try:
        root_mode = root.stat().st_mode
    except FileNotFoundError:
        if root.is_symlink():
            return Check(
                name="ledger root",
                status="fail",
                message=f"{path} (source: {source}) is a broken symlink.",
                hint=(
                    "Repair the symlink or configure WORKLOG_DIR to a usable "
                    "directory."
                ),
            )
        return Check(
            name="ledger root",
            status="ok",
            message=(
                f"{path} (source: {source}) does not exist yet; it will be "
                "created on first write."
            ),
        )
    except OSError as error:
        return Check(
            name="ledger root",
            status="fail",
            message=(
                f"Could not inspect {path} (source: {source}; "
                f"{_error_text(error)})."
            ),
            hint="Grant the current user access to the configured ledger path.",
        )
    if not stat.S_ISDIR(root_mode):
        return Check(
            name="ledger root",
            status="fail",
            message=f"{path} (source: {source}) exists but is not a directory.",
            hint="Configure WORKLOG_DIR to a directory or remove the conflicting path.",
        )

    error = _writability_error(root)
    if error is not None:
        return Check(
            name="ledger root",
            status="fail",
            message=f"{path} (source: {source}) exists but is not writable ({error}).",
            hint="Grant the current user write access to the ledger root.",
        )
    return Check(
        name="ledger root",
        status="ok",
        message=f"{path} (source: {source}) exists and a write probe succeeded.",
    )


def _scan_session_tree(root: Path) -> tuple[list[Path], list[Path], list[str]]:
    sessions = root / "sessions"
    agent_directories: list[Path] = []
    session_files: list[Path] = []
    problems: list[str] = []

    try:
        sessions_mode = sessions.stat().st_mode
    except FileNotFoundError:
        if sessions.is_symlink():
            problems.append(f"{_path_text(sessions)} is a broken symlink")
        return agent_directories, session_files, problems
    except OSError as error:
        problems.append(
            f"could not inspect {_path_text(sessions)} ({_error_text(error)})"
        )
        return agent_directories, session_files, problems
    if not stat.S_ISDIR(sessions_mode):
        problems.append(f"{_path_text(sessions)} is not a directory")
        return agent_directories, session_files, problems

    try:
        children = sorted(sessions.iterdir(), key=lambda path: str(path))
    except OSError as error:
        problems.append(f"could not scan {_path_text(sessions)} ({_error_text(error)})")
        return agent_directories, session_files, problems

    for child in children:
        try:
            is_directory = child.is_dir()
        except OSError as error:
            problems.append(
                f"could not inspect {_path_text(child)} ({_error_text(error)})"
            )
            continue
        if not is_directory:
            if child.is_symlink():
                problems.append(f"{_path_text(child)} is not a usable agent directory")
            continue

        agent_directories.append(child)
        try:
            candidates = sorted(child.iterdir(), key=lambda path: str(path))
        except OSError as error:
            problems.append(
                f"could not scan {_path_text(child)} ({_error_text(error)})"
            )
            continue
        for candidate in candidates:
            if candidate.suffix != ".md":
                continue
            try:
                is_file = candidate.is_file()
            except OSError as error:
                problems.append(
                    f"could not inspect {_path_text(candidate)} ({_error_text(error)})"
                )
                continue
            if is_file:
                session_files.append(candidate)
            else:
                problems.append(f"{_path_text(candidate)} is not a usable session file")

    return agent_directories, session_files, problems


def _summarize_paths(paths: list[Path], *, limit: int = 3) -> str:
    names = ", ".join(_path_text(path) for path in paths[:limit])
    remaining = len(paths) - limit
    if remaining > 0:
        names += f", and {remaining} more"
    return names


def _summarize_problems(problems: list[str], *, limit: int = 3) -> str:
    summary = "; ".join(problems[:limit])
    remaining = len(problems) - limit
    if remaining > 0:
        summary += f"; and {remaining} more"
    return summary


def _chmod_hint(directories: list[Path], files: list[Path]) -> str:
    commands: list[str] = []
    if directories:
        arguments = " ".join(shlex.quote(str(path)) for path in directories[:3])
        commands.append(f"chmod 700 {arguments}")
    if files:
        arguments = " ".join(shlex.quote(str(path)) for path in files[:3])
        commands.append(f"chmod 600 {arguments}")
    hint = "; ".join(commands)
    if len(directories) > 3 or len(files) > 3:
        hint += "; repeat for the remaining reported paths"
    return hint


def _check_permissions() -> Check:
    root = ledger_root()
    try:
        root_mode = root.stat().st_mode
    except FileNotFoundError:
        return Check(
            name="permissions",
            status="ok",
            message=(
                "Ledger root does not exist yet; there are no permissions to "
                "inspect."
            ),
        )
    except OSError as error:
        return Check(
            name="permissions",
            status="warn",
            message=f"Could not inspect ledger permissions ({_error_text(error)}).",
            hint="Grant the current user access to the configured ledger path.",
        )
    if not stat.S_ISDIR(root_mode):
        return Check(
            name="permissions",
            status="warn",
            message=(
                "Permissions cannot be inspected because the ledger root is not "
                "a directory."
            ),
        )

    agent_directories, session_files, problems = _scan_session_tree(root)
    directories = [root]
    sessions = root / "sessions"
    try:
        sessions_is_directory = stat.S_ISDIR(sessions.stat().st_mode)
    except OSError:
        sessions_is_directory = False
    if sessions_is_directory:
        directories.append(sessions)
    directories.extend(agent_directories)

    loose_directories: list[Path] = []
    loose_files: list[Path] = []
    modes: dict[Path, int] = {}
    permission_targets = [
        *((path, 0o700, loose_directories) for path in directories),
        *((path, 0o600, loose_files) for path in session_files),
    ]
    for path, expected, collection in permission_targets:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as error:
            problems.append(f"could not stat {_path_text(path)} ({_error_text(error)})")
            continue
        if mode != expected:
            collection.append(path)
            modes[path] = mode

    if loose_directories or loose_files:
        offenders = loose_directories + loose_files
        rendered = [
            f"{_path_text(path)} ({modes[path]:04o})" for path in offenders[:3]
        ]
        remaining = len(offenders) - 3
        message = "Expected private modes 0700/0600; found " + ", ".join(rendered)
        if remaining > 0:
            message += f", and {remaining} more"
        if problems:
            message += f". Other inspection problems: {_summarize_problems(problems)}"
        return Check(
            name="permissions",
            status="warn",
            message=message + ".",
            hint=_chmod_hint(loose_directories, loose_files),
        )
    if problems:
        return Check(
            name="permissions",
            status="warn",
            message=(
                "Permission inspection was incomplete: "
                f"{_summarize_problems(problems)}."
            ),
            hint="Repair the listed paths and rerun doctor.",
        )
    return Check(
        name="permissions",
        status="ok",
        message=(
            f"Private modes are correct on {len(directories)} director"
            f"{'y' if len(directories) == 1 else 'ies'} and "
            f"{len(session_files)} session "
            f"file{'s' if len(session_files) != 1 else ''}."
        ),
    )


def _check_ledger_contents() -> Check:
    root = ledger_root()
    _, session_files, problems = _scan_session_tree(root)
    entries = collect_entries(root)
    agents = {entry.agent for entry in entries}
    projects = {entry.project for entry in entries}
    newest = entries[0].timestamp if entries else "none"
    message = (
        f"{len(session_files)} session file(s), {len(entries)} checkpoint(s), "
        f"{len(agents)} distinct agent(s), {len(projects)} distinct project(s); "
        f"newest checkpoint: {newest}."
    )
    if problems:
        return Check(
            name="ledger contents",
            status="warn",
            message=f"{message} Scan incomplete: {_summarize_problems(problems)}.",
            hint="Repair the listed paths and rerun doctor for complete counts.",
        )
    return Check(name="ledger contents", status="ok", message=message)


def _check_unparsable_files() -> Check:
    _, session_files, problems = _scan_session_tree(ledger_root())
    unparsable = [path for path in session_files if not parse_session_file(path)]
    if unparsable:
        message = (
            f"{len(unparsable)} session file(s) yielded no checkpoints: "
            f"{_summarize_paths(unparsable)}."
        )
        if problems:
            message += f" Scan incomplete: {_summarize_problems(problems)}."
        return Check(
            name="unparsable files",
            status="warn",
            message=message,
            hint="These files are invisible to the viewer; repair or re-import them.",
        )
    if problems:
        return Check(
            name="unparsable files",
            status="warn",
            message=(
                "No unparsable files found, but the scan was incomplete: "
                f"{_summarize_problems(problems)}."
            ),
            hint="Repair the listed paths and rerun doctor.",
        )
    return Check(
        name="unparsable files",
        status="ok",
        message="All session files yielded at least one checkpoint.",
    )


def _contains_worklog_hook(value: object) -> bool:
    if isinstance(value, str):
        return "worklog.hook" in value.casefold()
    if isinstance(value, dict):
        return any(
            _contains_worklog_hook(key) or _contains_worklog_hook(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_worklog_hook(item) for item in value)
    return False


def _valid_user_prompt_response(response: object) -> bool:
    if not isinstance(response, dict):
        return False
    output = response.get("hookSpecificOutput")
    if not isinstance(output, dict):
        return False
    context = output.get("additionalContext")
    return (
        output.get("hookEventName") == "UserPromptSubmit"
        and isinstance(context, str)
        and "worklog add" in context.casefold()
    )


def _check_claude_hook() -> Check:
    settings = Path.home() / ".claude" / "settings.json"
    install_hint = (
        "Add a UserPromptSubmit hook that invokes worklog to "
        f"{_path_text(settings)}."
    )
    try:
        with settings.open(encoding="utf-8") as handle:
            configuration = json.load(handle)
    except FileNotFoundError:
        description = (
            f"{_path_text(settings)} is a broken symlink."
            if settings.is_symlink()
            else f"{_path_text(settings)} does not exist."
        )
        return Check(
            name="claude code hook",
            status="warn",
            message=description,
            hint=install_hint,
        )
    except json.JSONDecodeError as error:
        return Check(
            name="claude code hook",
            status="warn",
            message=f"Claude Code settings contain malformed JSON ({error}).",
            hint=(
                f"Repair the JSON in {_path_text(settings)}, then add a "
                "UserPromptSubmit hook that invokes worklog."
            ),
        )
    except (OSError, UnicodeError) as error:
        return Check(
            name="claude code hook",
            status="warn",
            message=f"Could not read {_path_text(settings)} ({_error_text(error)}).",
            hint=install_hint,
        )

    user_prompt_hooks: object = None
    if isinstance(configuration, dict):
        hooks = configuration.get("hooks")
        if isinstance(hooks, dict):
            user_prompt_hooks = hooks.get("UserPromptSubmit")
    if _contains_worklog_hook(user_prompt_hooks):
        response = build_response("worklog-doctor")
        if _valid_user_prompt_response(response):
            return Check(
                name="claude code hook",
                status="ok",
                message=(
                    "A worklog UserPromptSubmit hook is registered and emits "
                    "valid Claude Code context."
                ),
            )
        return Check(
            name="claude code hook",
            status="warn",
            message=(
                "The worklog UserPromptSubmit hook is registered, but its "
                "response does not match the Claude Code hook protocol."
            ),
            hint="Reinstall or update worklog, then rerun doctor.",
        )
    return Check(
        name="claude code hook",
        status="warn",
        message="No worklog UserPromptSubmit hook is registered.",
        hint=install_hint,
    )


def _hook_state_summary() -> tuple[int, bool]:
    """Return tracked session count and whether compaction detection is live."""
    sessions = 0
    saw_transcript_path = False
    for entry in hook_state_dir().iterdir():
        if not entry.is_file():
            continue
        sessions += 1
        try:
            with entry.open(encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(state, dict) and state.get("saw_transcript_path"):
            saw_transcript_path = True
    return sessions, saw_transcript_path


def _check_hook_context() -> Check:
    directory = hook_state_dir()
    saved = len(build_context("session")) - len(build_terse_context("session"))
    try:
        ensure_private_dir(directory)
        sessions, saw_transcript_path = _hook_state_summary()
    except OSError as error:
        return Check(
            name="hook context",
            status="warn",
            message=(
                f"Could not use {_path_text(directory)} ({_error_text(error)}); "
                "every prompt will carry the full checkpoint instruction."
            ),
            hint=(
                "Make the directory writable, or set WORKLOG_STATE_DIR to a "
                "writable path, to shorten repeat prompts."
            ),
        )

    detail = (
        "compaction re-sends the full rule"
        if saw_transcript_path
        else "no transcript path seen yet, so the full rule re-sends every "
        f"{REASSERT_EVERY_TURNS} turns"
    )
    return Check(
        name="hook context",
        status="ok",
        message=(
            f"Repeat prompts drop about {saved} characters of instruction "
            f"({sessions} session(s) tracked in {_path_text(directory)}; "
            f"{detail})."
        ),
    )


def _check_codex_adapter() -> Check:
    instructions = Path.home() / ".codex" / "AGENTS.md"
    hint = f"Add worklog checkpoint instructions to {_path_text(instructions)}."
    try:
        configured = "worklog" in instructions.read_text(encoding="utf-8").casefold()
    except FileNotFoundError:
        description = (
            f"{_path_text(instructions)} is a broken symlink."
            if instructions.is_symlink()
            else f"{_path_text(instructions)} does not exist."
        )
        return Check(
            name="codex adapter",
            status="warn",
            message=description,
            hint=hint,
        )
    except (OSError, UnicodeError) as error:
        return Check(
            name="codex adapter",
            status="warn",
            message=(
                f"Could not read {_path_text(instructions)} "
                f"({_error_text(error)})."
            ),
            hint=hint,
        )
    if configured:
        return Check(
            name="codex adapter",
            status="ok",
            message=f"{_path_text(instructions)} mentions worklog.",
        )
    return Check(
        name="codex adapter",
        status="warn",
        message=f"{_path_text(instructions)} does not mention worklog.",
        hint=hint,
    )


def _check_redactor() -> Check:
    configured = os.environ.get("WORKLOG_REDACTOR")
    if not configured:
        return Check(
            name="redactor",
            status="ok",
            message="WORKLOG_REDACTOR is not set; the built-in redactor is active.",
        )

    target = Path(configured).expanduser()
    path = _path_text(target)
    if target.is_file() and os.access(target, os.X_OK):
        return Check(
            name="redactor",
            status="ok",
            message=f"WORKLOG_REDACTOR is set to an existing executable file: {path}.",
        )
    return Check(
        name="redactor",
        status="warn",
        message=(
            "WORKLOG_REDACTOR is set, but its target is not an existing executable "
            f"file: {path}. The built-in redactor will be used."
        ),
        hint="Unset WORKLOG_REDACTOR or point it to an executable file.",
    )


def _check_git() -> Check:
    executable = shutil.which("git")
    if executable is None:
        return Check(
            name="git",
            status="warn",
            message="git is not on PATH; records will omit branch and commit metadata.",
            hint="Install git or add its executable directory to PATH.",
        )
    return Check(
        name="git",
        status="ok",
        message=f"git is available at {_path_text(Path(executable))}.",
    )


def run_checks() -> list[Check]:
    """Run every diagnostic check, isolating failures between checks."""
    checks: tuple[tuple[str, Callable[[], Check]], ...] = (
        ("python version", _check_python_version),
        ("ledger root", _check_ledger_root),
        ("permissions", _check_permissions),
        ("ledger contents", _check_ledger_contents),
        ("unparsable files", _check_unparsable_files),
        ("claude code hook", _check_claude_hook),
        ("hook context", _check_hook_context),
        ("codex adapter", _check_codex_adapter),
        ("redactor", _check_redactor),
        ("git", _check_git),
    )
    return [_safe_check(name, check) for name, check in checks]


def render_checks(checks: list[Check]) -> str:
    """Render diagnostic results as an aligned plain-text report."""
    if not checks:
        return "No checks were run."
    width = max(len(check.name) for check in checks)
    markers = {"ok": "ok", "warn": "warn", "fail": "FAIL"}
    lines: list[str] = []
    for check in checks:
        marker = markers.get(check.status, "FAIL")
        lines.append(f"{marker:<4}  {check.name:<{width}}  {check.message}")
        if check.hint:
            lines.append(f"{'':<4}  {'':<{width}}  hint: {check.hint}")
    return "\n".join(lines)


def worst_status(checks: list[Check]) -> str:
    """Return the most severe status present in diagnostic results."""
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"
