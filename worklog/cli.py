"""Command-line interface for worklog."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .doctor import render_checks, run_checks, worst_status
from .importer import ImportResult, import_ledger
from .paths import ledger_root
from .record import record
from .report import build_report, write_report
from .schedule import ScheduleResult, install_schedule, uninstall_schedule
from .view import collect_entries, filter_entries, parse_since, render


def _add_viewer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--since")
    parser.add_argument("--agent")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--today", action="store_true")


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    inferred_agent = "agent"
    if os.environ.get("CODEX_THREAD_ID"):
        inferred_agent = "codex"
    elif os.environ.get("CLAUDE_CODE_ENTRYPOINT") or os.environ.get(
        "CLAUDE_SESSION_ID"
    ):
        inferred_agent = "claude"

    parser = argparse.ArgumentParser(
        prog="worklog",
        description="Record verified work in the shared session worklog.",
    )
    _add_viewer_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser(
        "add", description="Record verified work in the shared session worklog."
    )
    add_parser.add_argument("--agent", default=inferred_agent)
    add_parser.add_argument("--session-id")
    add_parser.add_argument("--cwd", default=os.getcwd())
    add_parser.add_argument("--project")
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--done", action="append", default=[])
    add_parser.add_argument("--evidence", action="append", default=[])
    add_parser.add_argument("--allow-no-evidence", action="store_true")
    add_parser.add_argument("--remaining", action="append", default=[])
    add_parser.add_argument("--status", choices=("completed", "partial"))

    subparsers.add_parser("where", help="Print the resolved ledger root.")
    import_parser = subparsers.add_parser(
        "import", help="Import an existing accomplishment ledger."
    )
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--dest", type=Path)
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument(
        "--on-conflict",
        choices=("skip", "replace", "rename", "merge"),
        default="skip",
    )
    doctor_parser = subparsers.add_parser(
        "doctor", help="Diagnose worklog installation and configuration."
    )
    doctor_parser.add_argument("--json", action="store_true")
    list_parser = subparsers.add_parser(
        "list", help="List recent session worklog checkpoints."
    )
    _add_viewer_arguments(list_parser)
    report_parser = subparsers.add_parser(
        "report", help="Build a Markdown report for a time window."
    )
    report_parser.add_argument("--since", default="today")
    report_parser.add_argument("--until")
    report_parser.add_argument("--write", action="store_true")
    report_parser.add_argument("--quiet", action="store_true")
    install_report_parser = subparsers.add_parser(
        "install-report", help="Install the nightly report schedule."
    )
    install_report_parser.add_argument("--at", required=True)
    install_report_parser.add_argument("--dry-run", action="store_true")
    uninstall_report_parser = subparsers.add_parser(
        "uninstall-report", help="Remove the nightly report schedule."
    )
    uninstall_report_parser.add_argument("--dry-run", action="store_true")
    return parser, add_parser


def _run_viewer(args: argparse.Namespace) -> int:
    since_value = "today" if args.today else args.since
    try:
        since = parse_since(since_value) if since_value is not None else None
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    entries = filter_entries(
        collect_entries(),
        since=since,
        agent=args.agent,
        project=args.project,
    )
    selected = entries[: max(args.limit, 0)]
    if args.json:
        print(json.dumps([asdict(entry) for entry in selected], sort_keys=True))
    elif selected:
        print(render(selected))
    else:
        print("No worklog entries yet.")
    return 0


def _print_import_summary(result: ImportResult) -> None:
    if result.dry_run:
        print("DRY RUN — no files were written.")
    print(f"Files imported: {result.imported_files}")
    print(f"Checkpoints imported: {result.imported_checkpoints}")
    print(f"Skipped (existing): {result.skipped_existing}")
    print(f"Skipped (unparsable): {result.skipped_unparsable}")
    print(f"Errors: {len(result.errors)}")
    for error in result.errors:
        print(f"  - {error}")


def _run_import(args: argparse.Namespace) -> int:
    try:
        result = import_ledger(
            args.source,
            dest=args.dest,
            dry_run=args.dry_run,
            on_conflict=args.on_conflict,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    _print_import_summary(result)
    return 1 if result.errors else 0


def _run_doctor(args: argparse.Namespace) -> int:
    checks = run_checks()
    if args.json:
        print(json.dumps([asdict(check) for check in checks], sort_keys=True))
    else:
        print(render_checks(checks))
    return 1 if worst_status(checks) == "fail" else 0


def _run_report(args: argparse.Namespace) -> int:
    try:
        since = parse_since(args.since)
        until = parse_since(args.until) if args.until is not None else None
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    entries = filter_entries(collect_entries(), since=since, until=until)
    text = build_report(entries, since=since, until=until)
    path = None
    if args.write:
        path = write_report(text, day=dt.datetime.now().astimezone().date())

    if not args.quiet:
        print(text, end="")
        if path is not None:
            print(path)
    return 0


def _print_schedule_result(result: ScheduleResult, *, show_content: bool) -> None:
    print(result.message)
    if result.path is not None:
        print(f"Path: {result.path}")
    if show_content and result.content:
        print(result.content, end="" if result.content.endswith("\n") else "\n")


def _run_install_report(args: argparse.Namespace) -> int:
    try:
        result = install_schedule(at=args.at, dry_run=args.dry_run)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    _print_schedule_result(result, show_content=args.dry_run)
    return 0


def _run_uninstall_report(args: argparse.Namespace) -> int:
    try:
        result = uninstall_schedule(dry_run=args.dry_run)
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    _print_schedule_result(result, show_content=args.dry_run)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklog command-line interface."""
    parser, add_parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "list"):
        return _run_viewer(args)
    if args.command == "where":
        print(ledger_root())
        return 0
    if args.command == "import":
        return _run_import(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "report":
        return _run_report(args)
    if args.command == "install-report":
        return _run_install_report(args)
    if args.command == "uninstall-report":
        return _run_uninstall_report(args)
    if not args.done:
        add_parser.error("at least one --done item is required")

    try:
        path = record(
            agent=args.agent,
            session_id=args.session_id,
            cwd=args.cwd,
            project=args.project,
            title=args.title,
            done=args.done,
            evidence=args.evidence,
            allow_no_evidence=args.allow_no_evidence,
            remaining=args.remaining,
            status=args.status,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    print(f"Recorded accomplishments: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
