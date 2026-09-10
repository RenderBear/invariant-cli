from __future__ import annotations

import argparse

from invariant.mechanics import config, git


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("config", help="Inspect and update repository defaults")
    commands = parser.add_subparsers(dest="config_command", required=True)

    show = commands.add_parser("show", help="Show effective settings without creating a file")
    show.set_defaults(_handler=_show, _command="config.show")

    initialize = commands.add_parser("init", help="Persist every effective default")
    initialize.set_defaults(_handler=_init, _command="config.init")

    update = commands.add_parser("set", help="Update one validated tracked setting")
    update.add_argument("key", help="setting name")
    update.add_argument("value", help="new value")
    update.set_defaults(_handler=_set, _command="config.set")


def _repo():
    return git.root()


def _show(_: argparse.Namespace) -> list[str]:
    return config.lines(config.resolve(_repo()))


def _init(_: argparse.Namespace) -> list[str]:
    repo = _repo()
    git.require_capabilities(repo)
    return config.initialize(repo)


def _set(args: argparse.Namespace) -> list[str]:
    return config.set_value(_repo(), args.key, args.value)
