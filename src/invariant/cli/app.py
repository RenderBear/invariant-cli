from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from invariant import __version__
from invariant.cli.commands import (
    candidate,
    configuration,
    context,
    coordinate,
    evidence,
    governance,
    initialize,
    overview,
    state,
    task,
)
from invariant.cli.output import CommandResult, emit_error, emit_success
from invariant.errors import InvariantError, UsageError


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(f"Invariant: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="invariant", description="Preserve durable architectural intent")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="include the complete text rendering in JSON responses",
    )
    parser.add_argument("--version", action="version", version=f"invariant {__version__}")
    subparsers = parser.add_subparsers(dest="group", required=True, parser_class=Parser)
    initialize.register(subparsers)
    overview.register(subparsers)
    configuration.register(subparsers)
    task.register(subparsers)
    governance.register(subparsers)
    state.register(subparsers)
    context.register(subparsers)
    evidence.register(subparsers)
    coordinate.register(subparsers)
    candidate.register(subparsers)
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    command = "unknown"
    format_name = "text"
    try:
        args = parser.parse_args(argv)
        format_name = args.format
        command = args._command
        handler: Callable[[argparse.Namespace], list[str] | CommandResult] = args._handler
        return emit_success(command, handler(args), format_name, verbose=args.verbose)
    except InvariantError as exc:
        return emit_error(command, exc, format_name, verbose="args" in locals() and args.verbose)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
