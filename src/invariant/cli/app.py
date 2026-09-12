from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback
import uuid
from typing import Any

from invariant import __version__
from invariant.application import InvariantApplication, OperationResult
from invariant.cli.output import emit, emit_error
from invariant.errors import InvariantError, UsageError


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(f"Invariant: {message}")


def _operation(value: str | None) -> str:
    return value or f"op-{uuid.uuid4().hex}"


def _mutating(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--operation-id")


def _scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--interface", action="append", default=[])
    parser.add_argument("--domain", action="append", default=[])
    parser.add_argument("--contract", action="append", default=[])


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="invariant",
        description="Govern agentic work with a semantic kernel and Git-grounded lifecycle",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--version", action="version", version=f"invariant {__version__}")
    groups = parser.add_subparsers(dest="group", required=True, parser_class=Parser)

    init = groups.add_parser("init")
    init.add_argument("--defaults", action="store_true")

    status = groups.add_parser("status")

    governance = groups.add_parser("governance")
    governance_commands = governance.add_subparsers(dest="subcommand", required=True)
    explain = governance_commands.add_parser("explain")
    _scope(explain)
    explain.add_argument("--capability")
    explain.add_argument("--at")

    change = groups.add_parser("change")
    change_commands = change.add_subparsers(dest="subcommand", required=True)
    opened = change_commands.add_parser("open")
    opened.add_argument("change_id")
    opened.add_argument("--intent", required=True)
    opened.add_argument("--supplier", default="user:cli")
    _scope(opened)
    _mutating(opened)
    recommend = change_commands.add_parser("recommend")
    recommend.add_argument("change_id")
    recommend.add_argument("--host-capacity", type=int)
    _mutating(recommend)
    inspect = change_commands.add_parser("inspect")
    inspect.add_argument("change_id")
    handoff = change_commands.add_parser("handoff")
    handoff.add_argument("change_id")
    resume = change_commands.add_parser("resume")
    resume.add_argument("capsule")
    resume.add_argument("--actor", default="harness:cli")
    _mutating(resume)
    invalidate = change_commands.add_parser("invalidate")
    invalidate.add_argument("change_id")
    invalidate.add_argument("--token", required=True)
    invalidate.add_argument("--actor", required=True)
    invalidate.add_argument("--reason", required=True)
    _mutating(invalidate)

    action = groups.add_parser("action")
    action_commands = action.add_subparsers(dest="subcommand", required=True)
    action_inspect = action_commands.add_parser("inspect")
    action_inspect.add_argument("change_id")
    action_inspect.add_argument("action_id")
    respond = action_commands.add_parser("respond")
    respond.add_argument("change_id")
    respond.add_argument("action_id")
    respond.add_argument("--input", required=True)
    respond.add_argument("--actor", required=True)
    respond.add_argument("--token")
    _mutating(respond)

    capability = groups.add_parser("capability")
    capability_commands = capability.add_subparsers(dest="subcommand", required=True)
    request = capability_commands.add_parser("request")
    request.add_argument("change_id")
    request.add_argument("capability")
    request.add_argument("--actor", required=True)
    request.add_argument("--resource", required=True)
    request.add_argument("--unit")
    request.add_argument("--attempt")
    request.add_argument("--reason")
    request.add_argument("--expected-ledger")
    _mutating(request)
    capability_inspect = capability_commands.add_parser("inspect")
    capability_inspect.add_argument("change_id")
    capability_inspect.add_argument("identifier")
    revoke = capability_commands.add_parser("revoke")
    revoke.add_argument("change_id")
    revoke.add_argument("grant_id")
    revoke.add_argument("--actor", required=True)
    revoke.add_argument("--reason", required=True)
    _mutating(revoke)

    work = groups.add_parser("work")
    work_commands = work.add_subparsers(dest="subcommand", required=True)
    create = work_commands.add_parser("create")
    create.add_argument("change_id")
    create.add_argument("unit_id")
    create.add_argument("attempt_id")
    create.add_argument("--actor", required=True)
    create.add_argument("--token", required=True)
    _mutating(create)
    submit = work_commands.add_parser("submit")
    submit.add_argument("change_id")
    submit.add_argument("attempt_id")
    submit.add_argument("--actor", required=True)
    _mutating(submit)
    discard = work_commands.add_parser("discard")
    discard.add_argument("change_id")
    discard.add_argument("--ref", action="append", required=True)
    discard.add_argument("--token", required=True)
    _mutating(discard)

    candidate = groups.add_parser("candidate")
    candidate_commands = candidate.add_subparsers(dest="subcommand", required=True)
    converge = candidate_commands.add_parser("converge")
    converge.add_argument("change_id")
    converge.add_argument("attempt_id")
    converge.add_argument("--token", required=True)
    _mutating(converge)
    evidence = candidate_commands.add_parser("evidence")
    evidence.add_argument("change_id")
    evidence.add_argument(
        "--grants",
        help="JSON object mapping verifier locators to tokens",
    )
    _mutating(evidence)

    integration = groups.add_parser("integration")
    integration_commands = integration.add_subparsers(dest="subcommand", required=True)
    land = integration_commands.add_parser("land")
    land.add_argument("change_id")
    land.add_argument("--token", required=True)
    land.add_argument("--subject")
    _mutating(land)
    reconcile = integration_commands.add_parser("reconcile")
    reconcile.add_argument("change_id")
    _mutating(reconcile)

    publication = groups.add_parser("publication")
    publication_commands = publication.add_subparsers(dest="subcommand", required=True)
    publish = publication_commands.add_parser("publish")
    publish.add_argument("change_id")
    publish.add_argument("--token", required=True)
    _mutating(publish)

    return parser


def _read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"Invariant: cannot read JSON input '{path}': {exc}") from exc


def dispatch(args: argparse.Namespace) -> tuple[str, OperationResult]:
    if args.group == "init":
        return "init", InvariantApplication.initialize(".")
    app = InvariantApplication.bind(".", principal="user:cli")
    if args.group == "status":
        return "state.validate", app.state_validate()
    if args.group == "governance":
        return "governance.context", app.governance_context(
            paths=args.path,
            interfaces=args.interface,
            domains=args.domain,
            contracts=args.contract,
            capability=args.capability,
            at=args.at,
        )
    if args.group == "change":
        if args.subcommand == "open":
            return "change.open", app.change_open(
                args.change_id,
                intent=args.intent,
                supplier=args.supplier,
                paths=args.path,
                interfaces=args.interface,
                domains=args.domain,
                contracts=args.contract,
                operation_id=_operation(args.operation_id),
            )
        if args.subcommand == "recommend":
            return "change.recommend", app.change_recommend(
                args.change_id,
                operation_id=_operation(args.operation_id),
                host_capacity=args.host_capacity,
            )
        if args.subcommand == "inspect":
            return "change.inspect", app.change_inspect(args.change_id)
        if args.subcommand == "handoff":
            return "change.handoff", app.change_handoff(args.change_id)
        if args.subcommand == "resume":
            return "change.resume", app.change_resume(
                _read_json(args.capsule),
                actor=args.actor,
                operation_id=_operation(args.operation_id),
            )
        return "change.invalidate", app.change_invalidate(
            args.change_id,
            token=args.token,
            actor=args.actor,
            reason=args.reason,
            operation_id=_operation(args.operation_id),
        )
    if args.group == "action":
        if args.subcommand == "inspect":
            return "action.inspect", app.action_inspect(args.change_id, args.action_id)
        return "action.respond", app.action_respond(
            args.change_id,
            args.action_id,
            response=_read_json(args.input),
            actor=args.actor,
            token=args.token,
            operation_id=_operation(args.operation_id),
        )
    if args.group == "capability":
        if args.subcommand == "request":
            return "capability.request", app.capability_request(
                args.change_id,
                capability=args.capability,
                actor=args.actor,
                resource=args.resource,
                unit=args.unit,
                attempt=args.attempt,
                reason=args.reason,
                expected_ledger=args.expected_ledger,
                operation_id=_operation(args.operation_id),
            )
        if args.subcommand == "inspect":
            return "capability.inspect", app.capability_inspect(
                args.change_id, args.identifier
            )
        return "capability.revoke", app.capability_revoke(
            args.change_id,
            args.grant_id,
            actor=args.actor,
            reason=args.reason,
            operation_id=_operation(args.operation_id),
        )
    if args.group == "work":
        if args.subcommand == "create":
            return "work.create", app.work_create(
                args.change_id,
                unit_id=args.unit_id,
                attempt_id=args.attempt_id,
                actor=args.actor,
                token=args.token,
                operation_id=_operation(args.operation_id),
            )
        if args.subcommand == "submit":
            return "work.submit", app.work_submit(
                args.change_id,
                attempt_id=args.attempt_id,
                actor=args.actor,
                operation_id=_operation(args.operation_id),
            )
        return "work.discard", app.work_discard(
            args.change_id,
            refs=args.ref,
            token=args.token,
            operation_id=_operation(args.operation_id),
        )
    if args.group == "candidate":
        if args.subcommand == "converge":
            return "candidate.converge", app.candidate_converge(
                args.change_id,
                attempt_id=args.attempt_id,
                token=args.token,
                operation_id=_operation(args.operation_id),
            )
        grants = json.loads(args.grants) if args.grants else {}
        return "candidate.evidence", app.candidate_evidence(
            args.change_id,
            tokens=grants,
            operation_id=_operation(args.operation_id),
        )
    if args.group == "integration":
        if args.subcommand == "land":
            return "integration.land", app.integration_land(
                args.change_id,
                token=args.token,
                subject=args.subject,
                operation_id=_operation(args.operation_id),
            )
        return "integration.reconcile", app.integration_reconcile(
            args.change_id, operation_id=_operation(args.operation_id)
        )
    return "publication.publish", app.publication_publish(
        args.change_id,
        token=args.token,
        operation_id=_operation(args.operation_id),
    )


def _command_name(args: argparse.Namespace) -> str:
    if args.group == "init":
        return "init"
    if args.group == "status":
        return "state.validate"
    if args.group == "governance":
        return "governance.context"
    return f"{args.group}.{args.subcommand}"


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    command = "unknown"
    values = sys.argv[1:] if argv is None else argv
    format_name = "json"
    try:
        args = parser.parse_args(values)
        format_name = args.format
        command = _command_name(args)
        command, result = dispatch(args)
        return emit(command, result, format_name)
    except InvariantError as exc:
        return emit_error(command, exc, format_name)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return emit_error(
            command,
            InvariantError(
                f"Invariant: internal failure — {type(exc).__name__}: {exc}",
                code="internal_error",
            ),
            format_name,
        )


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
