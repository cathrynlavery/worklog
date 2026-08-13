"""Command-line interface for worklog."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict

from .paths import ledger_root
from .record import record
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
    add_parser.add_argument("--remaining", action="append", default=[])
    add_parser.add_argument("--status", choices=("completed", "partial"))

    subparsers.add_parser("where", help="Print the resolved ledger root.")
    list_parser = subparsers.add_parser(
        "list", help="List recent session worklog checkpoints."
    )
    _add_viewer_arguments(list_parser)
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklog command-line interface."""
    parser, add_parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "list"):
        return _run_viewer(args)
    if args.command == "where":
        print(ledger_root())
        return 0
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
