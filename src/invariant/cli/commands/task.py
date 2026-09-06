from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from invariant import adapters
from invariant.cli.output import CommandResult
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
        "--intent-brief-file",
        help="optional intent brief response; supplying it enables the adapter for this task",
    )
    begin.add_argument(
        "--intent-brief",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="override the configured intent brief adapter for this task",
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
        help="legacy low-level assessment input; normal task finish is CLI-managed",
    )
    finish.add_argument("--subject")
    finish.add_argument("--check", action="append", default=[])
    finish.set_defaults(_handler=_finish, _command="task.finish")

    respond = commands.add_parser(
        "respond", help="Resolve one structured lifecycle or adapter action"
    )
    respond.add_argument("task_id", help=TASK_ID_HELP)
    respond.add_argument("request_id", help="action id returned by begin or finish")
    respond.add_argument("--input", required=True, help="YAML or JSON response document")
    respond.set_defaults(_handler=_respond, _command="task.respond")

    continuation = commands.add_parser("continue")
    continuation.add_argument("task_id", help=TASK_ID_HELP)
    continuation.add_argument("--apply", action="store_true")
    continuation.set_defaults(_handler=_continue, _command="task.continue")

    invalidate = commands.add_parser("invalidate")
    invalidate.add_argument("task_id", help=TASK_ID_HELP)
    invalidate.set_defaults(_handler=_invalidate, _command="task.invalidate")

    guide = commands.add_parser("guidance")
    guide.add_argument("task_id", help=TASK_ID_HELP)
    guide.add_argument(
        "--full",
        action="store_true",
        help="include the detailed semantic reasoning and protocol handbook",
    )
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

    intent = commands.add_parser(
        "intent-brief", help="Inspect the bundled intent brief adapter protocol"
    )
    intents = intent.add_subparsers(dest="intent_command", required=True)
    intent_schema = intents.add_parser(
        "schema", help="Print the brief and review schemas"
    )
    intent_schema.set_defaults(
        _handler=_intent_schema, _command="task.intent-brief.schema"
    )
    intent_example = intents.add_parser(
        "example", help="Print prose-first brief and whole-candidate review examples"
    )
    intent_example.set_defaults(
        _handler=_intent_example, _command="task.intent-brief.example"
    )


def _repo():
    return git.root()


def _receipt_payload(task_id: str, receipt: dict[str, object]) -> dict[str, object]:
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
    change = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    return {
        "id": task_id,
        "stage": str(lifecycle.get("stage") or "briefed"),
        "goal_digest": str(receipt.get("goal_digest") or ""),
        "scope": {
            "paths": list(scope.get("paths", [])),
            "interfaces": list(scope.get("interfaces", [])),
            "domains": list(scope.get("domains", [])),
        },
        "boundary": str(change.get("boundary") or "unresolved"),
        "integration": {
            "target": str(receipt.get("integration_target") or ""),
            "base": str(receipt.get("integration_head") or ""),
        },
        "work": {
            "branch": str(lifecycle.get("branch") or ""),
            "worktree": str(lifecycle.get("worktree") or ""),
        },
        "adapters": list(adapters.enabled(receipt)),
        "actions": adapters.pending(receipt),
        "artifacts": receipt.get("hook_artifacts", []),
        "completion": {"commit": str(receipt.get("completed_commit") or "")},
    }


def _task_payload(repo: Path, task_id: str) -> dict[str, object]:
    return _receipt_payload(task_id, receipts.load(repo, task_id))


def _terminal_task_payload(
    repo: Path, task_id: str, stage: str = "completed"
) -> dict[str, object]:
    completed = receipts.load_completed(repo, task_id) if stage == "completed" else None
    if completed is not None:
        return _receipt_payload(task_id, completed)
    return {
        "id": task_id,
        "stage": stage,
        "goal_digest": "",
        "scope": {"paths": [], "interfaces": [], "domains": []},
        "boundary": "unresolved",
        "integration": {"target": "", "base": ""},
        "work": {"branch": "", "worktree": ""},
        "adapters": [],
        "actions": [],
        "artifacts": [],
        "completion": {"commit": ""},
    }


def _task_result(repo: Path, task_id: str, lines: list[str]) -> CommandResult:
    payload = _task_payload(repo, task_id)
    stage = str(payload["stage"])
    outcome = (
        "needs_input"
        if payload["actions"]
        else "awaiting_approval"
        if stage in {"awaiting-branch", "awaiting-landing"}
        else "ready"
    )
    return CommandResult(lines, {"task": payload}, outcome)


def _flow_result(
    repo: Path, task_id: str, result: tasks.FlowResult
) -> CommandResult:
    if receipts.receipt_path(repo, task_id).is_file():
        task_payload = _task_payload(repo, task_id)
    else:
        task_payload = _terminal_task_payload(repo, task_id)
    data: dict[str, object] = {"task": task_payload}
    candidate_tree = result.data.get("candidate_tree")
    evidence = result.data.get("evidence")
    if candidate_tree or evidence:
        data["candidate"] = {
            "tree": str(candidate_tree or ""),
            "evidence": evidence if isinstance(evidence, list) else [],
        }
    return CommandResult(result.lines, data, result.outcome)


def _begin(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    lines = tasks.begin(
        repo,
        args.task_id,
        goal=args.goal,
        boundary=args.boundary,
        paths=args.path,
        interfaces=args.interface,
        domains=args.domain,
        adapter_inputs={"intent_brief": args.intent_brief_file},
        adapter_overrides=(
            {"intent_brief": args.intent_brief}
            if args.intent_brief is not None
            else {}
        ),
    )
    return _task_result(repo, args.task_id, lines)


def _status(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    return _task_result(repo, args.task_id, tasks.status(repo, args.task_id))


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


def _finish(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    if args.assessment:
        lines = tasks.finish(
            repo,
            args.task_id,
            assessment_path=args.assessment,
            subject=args.subject,
            checks=args.check,
        )
        return CommandResult(
            lines, {"task": _terminal_task_payload(repo, args.task_id)}
        )
    result = tasks.prepare_finish(
        repo, args.task_id, subject=args.subject, checks=args.check
    )
    return _flow_result(repo, args.task_id, result)


def _respond(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    result = tasks.respond(repo, args.task_id, args.request_id, args.input)
    return _flow_result(repo, args.task_id, result)


def _continue(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    lines = tasks.continue_task(repo, args.task_id, apply=args.apply)
    if "STATUS: completed" in lines:
        return CommandResult(
            lines,
            {"task": _terminal_task_payload(repo, args.task_id)},
        )
    return _task_result(repo, args.task_id, lines)


def _invalidate(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    lines = tasks.invalidate(repo, args.task_id)
    return CommandResult(
        lines, {"task": _terminal_task_payload(repo, args.task_id, "invalidated")}
    )


def _guidance(args: argparse.Namespace) -> CommandResult:
    repo = _repo()
    lines = tasks.task_guidance(repo, args.task_id, full=args.full)
    return CommandResult(lines, {"task": _task_payload(repo, args.task_id), "guidance": "\n".join(lines)})


def _yaml_lines(value: object) -> list[str]:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip().splitlines()


def _assessment_schema(_: argparse.Namespace) -> CommandResult:
    value = schemas.assessment_schema()
    return CommandResult(_yaml_lines(value), {"schema": value})


def _assessment_example(_: argparse.Namespace) -> CommandResult:
    value = schemas.assessment_example()
    return CommandResult(_yaml_lines(value), {"example": value})


def _intent_schema(_: argparse.Namespace) -> CommandResult:
    value = adapters.schemas("intent_brief")
    return CommandResult(_yaml_lines(value), {"schema": value})


def _intent_example(_: argparse.Namespace) -> CommandResult:
    value = adapters.examples("intent_brief")
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
