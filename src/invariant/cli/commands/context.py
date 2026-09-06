from __future__ import annotations

import argparse

from invariant.errors import Blocked
from invariant.mechanics import git, governance


def _scope_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--root", action="store_true")
    parser.add_argument("--path", action="append")
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--interface", action="append", default=[])


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("context", help="Inspect reach and selected durable governance")
    commands = parser.add_subparsers(dest="context_command", required=True)
    mapping = commands.add_parser("map")
    mapping.set_defaults(_handler=lambda _: governance.context_map(git.root()), _command="context.map")
    rows = commands.add_parser("rows")
    rows.add_argument("domains", nargs="*")
    rows.set_defaults(_handler=_rows, _command="context.rows")
    digest = commands.add_parser("digest")
    digest.add_argument("domains", nargs="*")
    digest.add_argument("--at")
    digest.set_defaults(_handler=_digest, _command="context.digest")
    check = commands.add_parser("check-digest")
    check.add_argument("expected")
    check.add_argument("domains", nargs="*")
    check.set_defaults(_handler=_check_digest, _command="context.check-digest")
    reach = commands.add_parser("reach")
    _scope_options(reach)
    reach.set_defaults(_handler=_reach, _command="context.reach")
    verifiers = commands.add_parser("verifiers")
    _scope_options(verifiers)
    verifiers.set_defaults(_handler=_verifiers, _command="context.verifiers")
    material = commands.add_parser("material-changes")
    material.add_argument("base")
    material.add_argument("tip")
    material.add_argument("domains", nargs="*")
    material.set_defaults(_handler=_material, _command="context.material-changes")
    message = commands.add_parser("message")
    message.add_argument("subject")
    message.add_argument("--unit", action="append", required=True)
    message.add_argument("--scope", action="append", required=True)
    message.add_argument("--domain", action="append", default=[])
    message.add_argument("--plan")
    message.set_defaults(_handler=_message, _command="context.message")
    trailer = commands.add_parser("trailer")
    trailer.add_argument("commit")
    trailer.set_defaults(_handler=_trailer, _command="context.trailer")


def _rows(args: argparse.Namespace) -> list[str]:
    return governance.display_rows(git.root(), args.domains)


def _digest(args: argparse.Namespace) -> list[str]:
    return [f"DIGEST: {governance.digest(git.root(), args.domains, args.at)}"]


def _check_digest(args: argparse.Namespace) -> list[str]:
    actual = governance.digest(git.root(), args.domains)
    if actual != args.expected:
        raise Blocked(f"STALE: expected {args.expected} actual {actual}", code="stale_governance")
    return [f"DIGEST: fresh {actual}"]


def _reach(args: argparse.Namespace) -> list[str]:
    return governance.reach(
        git.root(),
        paths=args.path,
        domains_selected=args.domain,
        interfaces=args.interface,
        base=args.base,
        history=args.history,
        root_mode=args.root,
    )


def _verifiers(args: argparse.Namespace) -> list[str]:
    return governance.verifiers(
        git.root(),
        paths=args.path,
        domains_selected=args.domain,
        interfaces=args.interface,
        base=args.base,
        history=args.history,
        root_mode=args.root,
    )


def _material(args: argparse.Namespace) -> list[str]:
    return governance.material_changes(git.root(), args.base, args.tip, args.domains)


def _message(args: argparse.Namespace) -> list[str]:
    return governance.commit_message(
        git.root(), args.subject, args.unit, args.scope, args.domain, args.plan
    ).rstrip("\n").splitlines()


def _trailer(args: argparse.Namespace) -> list[str]:
    return governance.validate_trailer(git.root(), args.commit)
