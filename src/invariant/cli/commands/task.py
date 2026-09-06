from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from invariant import adapters
from invariant.cli.output import CommandResult
from invariant.errors import Blocked
from invariant.lifecycle import tasks
from invariant.mechanics import git, receipts
from invariant.mechanics.documents import dump_yaml
from invariant.semantics import schemas


TASK_ID_HELP = (
    "caller-chosen ID for one managed repository change "
    "(letters, numbers, dot, underscore, and hyphen)"
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("task", help="Manage the fixed repository task lifecycle")
    commands = parser.add_subparsers(dest="task_command", required=True)

    begin = commands.add_parser("begin")
    begin.add_argument("task_id", help=TASK_ID_HELP)
    begin.add_argument("--goal", required=True)
    begin.add_argument(
        "--boundary",
        default="unresolved",
        help="initial durable-meaning disposition (defaults to unresolved)",
    )
    begin.add_argument("--path", action="append", default=[])
    begin.add_argument("--interface", action="append", default=[])
    begin.add_argument("--domain", action="append", default=[])
    begin.add_argument(
        "--acceptance-contract",
        help="task acceptance adapter contract; supplying it enables the adapter for this task",
    )
    begin.add_argument(
        "--task-acceptance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="override the configured task acceptance adapter for this task",
    )
    begin.set_defaults(_handler=_begin, _command="task.begin")

    status = commands.add_parser("status")
    status.add_argument("task_id", help=TASK_ID_HELP)
    status.set_defaults(_handler=_status, _command="task.status")

    check = commands.add_parser("check")
    check.add_argument("task_id", help=TASK_ID_HELP)
    goal = check.add_mutually_exclusive_group(required=True)
    goal.add_argument("--goal")
    goal.add_argument("--goal-digest")
    check.add_argument("--compatible-goal", action="store_true")
    check.add_argument("--path", action="append")
    check.add_argument("--interface", action="append")
    check.add_argument("--domain", action="append")
    check.set_defaults(_handler=_check, _command="task.check")

    finish = commands.add_parser("finish")
    finish.add_argument("task_id", help=TASK_ID_HELP)
    finish.add_argument(
        "--assessment",
        help="assessment file (defaults to a Git-local draft, prepared automatically when absent)",
    )
    finish.add_argument("--subject")
    finish.add_argument("--check", action="append", default=[])
    finish.add_argument(
        "--acceptance-review",
        help="candidate-bound task acceptance review (defaults to the Git-local prepared review)",
    )
    finish.set_defaults(_handler=_finish, _command="task.finish")

    continuation = commands.add_parser("continue")
    continuation.add_argument("task_id", help=TASK_ID_HELP)
    continuation.add_argument("--apply", action="store_true")
    continuation.set_defaults(_handler=_continue, _command="task.continue")

    invalidate = commands.add_parser("invalidate")
    invalidate.add_argument("task_id", help=TASK_ID_HELP)
    invalidate.set_defaults(_handler=_invalidate, _command="task.invalidate")

    guide = commands.add_parser("guidance")
    guide.add_argument("task_id", help=TASK_ID_HELP)
    guide.set_defaults(_handler=_guidance, _command="task.guidance")

    assessment = commands.add_parser("assessment", help="Inspect or prepare task assessments")
    assessments = assessment.add_subparsers(dest="assessment_command", required=True)
    assessment_schema = assessments.add_parser("schema", help="Print the version-1 assessment schema")
    assessment_schema.set_defaults(
        _handler=_assessment_schema, _command="task.assessment.schema"
    )
    assessment_example = assessments.add_parser("example", help="Print a complete assessment example")
    assessment_example.set_defaults(
        _handler=_assessment_example, _command="task.assessment.example"
    )
    assessment_prepare = assessments.add_parser(
        "prepare", help="Generate a candidate-bound assessment draft and missing requirements"
    )
    assessment_prepare.add_argument("task_id", help=TASK_ID_HELP)
    assessment_prepare.add_argument("--output")
    assessment_prepare.set_defaults(
        _handler=_assessment_prepare, _command="task.assessment.prepare"
    )

    acceptance = commands.add_parser(
        "acceptance", help="Inspect the bundled task acceptance adapter protocol"
    )
    acceptances = acceptance.add_subparsers(dest="acceptance_command", required=True)
    acceptance_schema = acceptances.add_parser(
        "schema", help="Print the contract and review schemas"
    )
    acceptance_schema.set_defaults(
        _handler=_acceptance_schema, _command="task.acceptance.schema"
    )
    acceptance_example = acceptances.add_parser(
        "example", help="Print proportional contract and review examples"
    )
    acceptance_example.set_defaults(
        _handler=_acceptance_example, _command="task.acceptance.example"
    )


def _repo():
    return git.root()


def _begin(args: argparse.Namespace) -> list[str]:
    return tasks.begin(
        _repo(),
        args.task_id,
        goal=args.goal,
        boundary=args.boundary,
        paths=args.path,
        interfaces=args.interface,
        domains=args.domain,
        adapter_inputs={"task_acceptance": args.acceptance_contract},
        adapter_overrides=(
            {"task_acceptance": args.task_acceptance}
            if args.task_acceptance is not None
            else {}
        ),
    )


def _status(args: argparse.Namespace) -> list[str]:
    return tasks.status(_repo(), args.task_id)


def _check(args: argparse.Namespace) -> list[str]:
    return tasks.check(
        _repo(),
        args.task_id,
        goal=args.goal,
        goal_digest=args.goal_digest,
        compatible_goal=args.compatible_goal,
        paths=args.path,
        interfaces=args.interface,
        domains=args.domain,
    )


def _finish(args: argparse.Namespace) -> list[str]:
    repo = _repo()
    prepared = receipts.task_root(repo, args.task_id) / "prepared-assessment.yml"
    prefix: list[str] = []
    if not args.assessment and not prepared.is_file():
        assessment_value, analysis = tasks.prepare_assessment(repo, args.task_id)
        dump_yaml(prepared, assessment_value)
        lines, required = _preparation_lines(repo, args.task_id, prepared, analysis)
        if required:
            raise Blocked(
                "Invariant: the generated assessment needs semantic completion before landing",
                code="assessment_completion_required",
                lines=[
                    *lines,
                    f"NEXT: complete {prepared} and rerun invariant task finish {args.task_id}",
                ],
                data={
                    "assessment": assessment_value,
                    "analysis": analysis,
                    "path": str(prepared),
                },
            )
        prefix = [f"ASSESSMENT: inferred {args.task_id}"]
    assessment = args.assessment or str(prepared)
    return [
        *prefix,
        *tasks.finish(
            repo,
            args.task_id,
            assessment_path=assessment,
            subject=args.subject,
            checks=args.check,
            adapter_inputs={"task_acceptance": args.acceptance_review},
        ),
    ]


def _continue(args: argparse.Namespace) -> list[str]:
    return tasks.continue_task(_repo(), args.task_id, apply=args.apply)


def _invalidate(args: argparse.Namespace) -> list[str]:
    return tasks.invalidate(_repo(), args.task_id)


def _guidance(args: argparse.Namespace) -> list[str]:
    return tasks.task_guidance(_repo(), args.task_id)


def _yaml_lines(value: object) -> list[str]:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip().splitlines()


def _assessment_schema(_: argparse.Namespace) -> CommandResult:
    value = schemas.assessment_schema()
    return CommandResult(_yaml_lines(value), {"schema": value})


def _assessment_example(_: argparse.Namespace) -> CommandResult:
    value = schemas.assessment_example()
    return CommandResult(_yaml_lines(value), {"example": value})


def _acceptance_schema(_: argparse.Namespace) -> CommandResult:
    value = adapters.schemas()
    return CommandResult(_yaml_lines(value), {"schema": value})


def _acceptance_example(_: argparse.Namespace) -> CommandResult:
    value = adapters.task_acceptance_examples()
    return CommandResult(_yaml_lines(value), {"example": value})


def _assessment_prepare(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    assessment, analysis = tasks.prepare_assessment(repo, args.task_id)
    destination = (
        (repo / args.output).resolve()
        if args.output
        else receipts.task_root(repo, args.task_id) / "prepared-assessment.yml"
    )
    dump_yaml(destination, assessment)
    lines, _ = _preparation_lines(repo, args.task_id, destination, analysis)
    return CommandResult(
        lines,
        {"assessment": assessment, "analysis": analysis, "path": str(destination)},
    )


def _preparation_lines(
    repo: Path, task_id: str, destination: Path, analysis: dict[str, object]
) -> tuple[list[str], int]:
    try:
        display_path: object = destination.relative_to(repo)
    except ValueError:
        display_path = destination
    lines = [f"ASSESSMENT: prepared {task_id}", f"SAVED: {display_path}"]
    adapter_required = sum(
        len(item.get("required", []))
        for item in analysis.get("adapters", [])
        if isinstance(item, dict) and isinstance(item.get("required"), list)
    )
    semantic_required = analysis.get("required", [])
    if not isinstance(semantic_required, list):
        semantic_required = []
    if semantic_required or adapter_required:
        lines.append(
            f"REQUIRED: {len(semantic_required)} semantic completion(s), "
            f"{adapter_required} adapter result(s)"
        )
    else:
        lines.append("READY: assessment has no unresolved generated requirements")
    for item in semantic_required:
        if isinstance(item, dict):
            detail = (
                item.get("values")
                or item.get("allowed")
                or item.get("value_after_approval")
            )
            suffix = f" — {detail}" if detail else ""
            lines.append(
                f"REQUIRED-FIELD: {item.get('field', 'unknown')} — "
                f"{item.get('reason', 'completion required')}{suffix}"
            )
    for adapter in analysis.get("adapters", []):
        if isinstance(adapter, dict) and adapter.get("review"):
            lines.append(f"ADAPTER-REVIEW: {adapter['review']}")
    return lines, len(semantic_required) + adapter_required
