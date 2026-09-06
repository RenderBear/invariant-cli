from __future__ import annotations

import argparse

from invariant.errors import Blocked
from invariant.mechanics import config, git, state


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("state", help="Validate tracked Invariant state")
    commands = parser.add_subparsers(dest="state_command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--landing", action="store_true")
    validate.set_defaults(_handler=_validate, _command="state.validate")
    show = commands.add_parser("config")
    show.set_defaults(_handler=_config, _command="state.config")


def _validate(args: argparse.Namespace) -> list[str]:
    lines = state.validate(git.root(), landing=args.landing)
    if lines[-1].endswith("Invariant state violation(s)"):
        raise Blocked("Invariant: state validation failed", code="invalid_state", lines=lines)
    return lines


def _config(_: argparse.Namespace) -> list[str]:
    return config.lines(config.resolve(git.root()))
