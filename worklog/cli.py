"""Command-line interface for worklog."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from .paths import ledger_root
from .record import record


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
    return parser, add_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worklog command-line interface."""
    parser, add_parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
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
