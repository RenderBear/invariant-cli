from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from invariant.cli.argv import hoist_global_options, requested_format
from invariant.errors import InvariantError
from invariant.harness.providers import (
    AgentInvocationError,
    AgentProvider,
    invoke,
    status,
)
from invariant.mechanics import receipts
from invariant.mechanics.documents import load_yaml
from invariant.semantics import sources
from invariant.semantics.adoption import authoring_schema, projected_record_schema


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AgentInvocationError(message, code="invalid_invocation")


def _provider(value: str) -> AgentProvider:
    try:
        return AgentProvider(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use codex or claude") from None


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="invariant-agent",
        description="Connect Invariant to user-authenticated local coding agents",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    doctor = commands.add_parser("doctor", help="Inspect local coding-agent connections")
    doctor.add_argument("provider", nargs="?", type=_provider)
    doctor.set_defaults(handler=_doctor, command_name="agent.doctor")

    ask = commands.add_parser(
        "ask", help="Ask a local coding agent a read-only repository question"
    )
    _provider_arguments(ask)
    ask.add_argument(
        "--dry-run",
        action="store_true",
        help="show the request boundary without invoking the agent",
    )
    ask.add_argument("prompt")
    ask.set_defaults(handler=_ask, command_name="agent.ask")

    resolve = commands.add_parser(
        "resolve", help="Resolve a task's pending action with a local coding agent"
    )
    _agent_arguments(resolve)
    _review_arguments(resolve)
    resolve.add_argument(
        "--action",
        dest="action_id",
        help="pending action id; inferred when the task has exactly one",
    )
    resolve.add_argument("task_id")
    resolve.set_defaults(handler=_task_respond, command_name="agent.resolve")

    governance = commands.add_parser(
        "governance", help="Use an agent for repository governance semantics"
    )
    governance_commands = governance.add_subparsers(
        dest="governance_command", required=True, parser_class=Parser
    )
    audit = governance_commands.add_parser(
        "audit", help="Generate and save a read-only governance audit"
    )
    _agent_arguments(audit)
    audit.add_argument("task_id")
    audit.set_defaults(handler=_governance_audit, command_name="agent.governance.audit")
    author = governance_commands.add_parser(
        "author", help="Complete the unresolved record projections of an adoption draft"
    )
    _agent_arguments(author)
    author.add_argument("task_id")
    author.set_defaults(handler=_governance_author, command_name="agent.governance.author")

    task = commands.add_parser("task", help="Use an agent for pending lifecycle actions")
    task_commands = task.add_subparsers(
        dest="task_command", required=True, parser_class=Parser
    )
    respond = task_commands.add_parser(
        "respond", help="Low-level, scriptable form of resolve"
    )
    _agent_arguments(respond)
    _review_arguments(respond)
    respond.add_argument("task_id")
    respond.add_argument("action_id", nargs="?")
    respond.set_defaults(handler=_task_respond, command_name="agent.task.respond")
    return parser


def _review_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--independent",
        action="store_true",
        help=(
            "record the response as an independent review because this host routed the "
            "action away from the candidate's author"
        ),
    )


def _provider_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--using", required=True, type=_provider, metavar="codex|claude")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=600)


def _agent_arguments(parser: argparse.ArgumentParser) -> None:
    _provider_arguments(parser)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="invoke the agent and submit its result; omission prints a dry-run preview",
    )


def _repo() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise AgentInvocationError("not inside a Git repository", code="not_repository")
    return Path(completed.stdout.strip()).resolve()


def _invariant(repo: Path, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-P", "-m", "invariant", "--format", "json", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = (completed.stderr or completed.stdout).strip()
        raise AgentInvocationError(
            f"Invariant returned invalid JSON{': ' + detail if detail else ''}",
            code="invalid_invariant_output",
        ) from exc
    if not isinstance(payload, dict):
        raise AgentInvocationError(
            "Invariant returned a non-object response", code="invalid_invariant_output"
        )
    if completed.returncode:
        diagnostics = payload.get("diagnostics")
        message = "Invariant rejected the harness request"
        code = "invariant_rejected"
        if isinstance(diagnostics, list) and diagnostics and isinstance(diagnostics[0], dict):
            message = str(diagnostics[0].get("message") or message)
            code = str(diagnostics[0].get("code") or code)
        raise AgentInvocationError(
            message, code=code, exit_code=1 if completed.returncode == 1 else 2
        )
    return payload


def _result(payload: dict[str, Any], name: str) -> Any:
    result = payload.get("result")
    if not isinstance(result, dict) or name not in result:
        raise AgentInvocationError(
            f"Invariant response omitted result.{name}", code="invalid_invariant_output"
        )
    return result[name]


def _task_worktree(repo: Path, task_id: str) -> Path:
    task = _result(_invariant(repo, "task", "status", task_id), "task")
    if not isinstance(task, dict):
        raise AgentInvocationError(
            "Invariant returned an invalid task", code="invalid_invariant_output"
        )
    work = task.get("work")
    value = work.get("worktree") if isinstance(work, dict) else None
    path = Path(str(value or ""))
    if not path.is_dir():
        raise AgentInvocationError(
            f"task '{task_id}' has no available worktree", code="missing_task_worktree"
        )
    return path.resolve()


def _prompt(kind: str, request: dict[str, Any]) -> str:
    envelope = json.dumps(request, sort_keys=True, indent=2, ensure_ascii=False)
    return (
        "You are a read-only semantic worker dispatched by the Invariant harness.\n"
        "Do not modify files, create commits, or change repository state. Inspect the repository "
        "only as needed. Evidence is not authority: report uncertainty or missing authority "
        "instead of inventing a decision. Return exactly one JSON object matching the supplied "
        "schema. Preserve every schema const exactly.\n\n"
        f"Request kind: {kind}\n\n"
        "<invariant-request>\n"
        f"{envelope}\n"
        "</invariant-request>\n"
    )


def _preview(
    provider: AgentProvider,
    task_id: str | None,
    operation: str,
    cwd: Path,
    schema_id: str,
    prompt: str,
) -> dict[str, Any]:
    result = {
        "provider": provider.value,
        "operation": operation,
        "mode": "read-only",
        "cwd": str(cwd),
        "schema": schema_id,
        "prompt_digest": hashlib.sha256(prompt.encode()).hexdigest(),
        "applied": False,
    }
    if task_id is not None:
        result["task"] = task_id
    return result


def _invoke_and_submit(
    repo: Path,
    provider: AgentProvider,
    cwd: Path,
    prompt: str,
    schema: dict[str, Any],
    submit: tuple[str, ...],
    *,
    model: str | None,
    timeout: int,
    semantic_retries: int = 0,
    stamps: dict[str, str] | None = None,
) -> dict[str, Any]:
    if timeout <= 0:
        raise AgentInvocationError("timeout must be greater than zero", code="invalid_invocation")
    current_prompt = prompt
    usage: dict[str, Any] = {}
    for attempt in range(semantic_retries + 1):
        agent = invoke(
            provider,
            cwd,
            current_prompt,
            schema,
            model=model,
            timeout=timeout,
        )
        # Provenance is a fact about how this host dispatched the action, not a claim the
        # model gets to make about itself.
        for name, value in (stamps or {}).items():
            if name in agent.response:
                agent.response[name] = value
        for name, value in agent.usage.items():
            prior = usage.get(name)
            usage[name] = (
                prior + value
                if isinstance(prior, (int, float))
                and isinstance(value, (int, float))
                else value
            )
        with tempfile.TemporaryDirectory(prefix="invariant-agent-response.") as directory:
            response = Path(directory) / "response.json"
            response.write_text(
                json.dumps(agent.response, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                invariant = _invariant(repo, *submit, "--input", str(response))
            except AgentInvocationError as exc:
                if attempt >= semantic_retries or exc.code != "invalid_audit":
                    raise
                prior_response = json.dumps(
                    agent.response,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
                current_prompt = (
                    f"{prompt}\n\n"
                    "<invariant-validation-retry>\n"
                    "Invariant rejected the previous structured response. Correct only the "
                    "reported semantic or locator defect, then return the complete JSON object "
                    "again. Do not weaken, omit, or invent evidence.\n"
                    f"Rejection: {exc.message}\n"
                    f"Previous response:\n{prior_response}\n"
                    "</invariant-validation-retry>\n"
                )
                continue
        return {
            "provider": provider.value,
            "session_id": agent.session_id,
            "response_digest": hashlib.sha256(
                json.dumps(agent.response, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "usage": usage,
            "invariant": invariant,
            "applied": True,
        }
    raise AssertionError("unreachable semantic retry loop")


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    providers = [args.provider] if args.provider else list(AgentProvider)
    return {
        "providers": [
            {
                "provider": item.provider.value,
                "available": item.available,
                "executable": item.executable,
                "version": item.version,
                "hint": item.hint,
            }
            for item in (status(provider) for provider in providers)
        ]
    }


def _ask(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo()
    if not args.prompt.strip():
        raise AgentInvocationError("prompt cannot be empty", code="invalid_invocation")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["message"],
        "properties": {"message": {"type": "string", "minLength": 1}},
    }
    prompt = _prompt(
        "ask",
        {
            "prompt": args.prompt,
            "instructions": (
                "Answer the prompt directly. Use the repository as read-only context when useful."
            ),
        },
    )
    preview = _preview(
        args.using,
        None,
        "ask",
        repo,
        "invariant://schemas/agent-message/v1",
        prompt,
    )
    preview["invoked"] = False
    if args.dry_run:
        return preview
    if args.timeout <= 0:
        raise AgentInvocationError(
            "timeout must be greater than zero", code="invalid_invocation"
        )
    agent = invoke(
        args.using,
        repo,
        prompt,
        schema,
        model=args.model,
        timeout=args.timeout,
    )
    message = agent.response.get("message")
    if not isinstance(message, str) or not message:
        raise AgentInvocationError(
            f"{args.using.value} omitted its answer", code="invalid_agent_output"
        )
    return {
        **preview,
        "session_id": agent.session_id,
        "response_digest": hashlib.sha256(
            json.dumps(agent.response, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "usage": agent.usage,
        "message": message,
        "invoked": True,
    }


def _governance_audit(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo()
    cwd = _task_worktree(repo, args.task_id)
    schema = _result(_invariant(repo, "evidence", "audit", "schema"), "schema")
    if not isinstance(schema, dict):
        raise AgentInvocationError(
            "Invariant returned an invalid audit schema", code="invalid_invariant_output"
        )
    frame = _invariant(repo, "governance", "status", args.task_id)
    request = {
        "task": args.task_id,
        "authority": f"agent:{args.using.value}",
        "audit_frame": frame,
        "instructions": (
            "Investigate the repository-wide durable responsibilities, architecture, contracts, "
            "constraints, and executable witnesses. Use repository locators for evidence. Classify "
            "only grounded findings. Include complete record projections only when unambiguous."
        ),
    }
    try:
        grounding = sources.prompt_context(cwd)
    except InvariantError as exc:
        raise AgentInvocationError(exc.message, code=exc.code) from exc
    if grounding:
        request["grounding_sources"] = grounding
    prompt = _prompt("governance.audit", request)
    preview = _preview(
        args.using,
        args.task_id,
        "governance.audit",
        cwd,
        "invariant://schemas/audit-findings/v1",
        prompt,
    )
    if not args.apply:
        return preview
    return {
        **preview,
        **_invoke_and_submit(
            repo,
            args.using,
            cwd,
            prompt,
            schema,
            ("governance", "audit-save", args.task_id),
            model=args.model,
            timeout=args.timeout,
            semantic_retries=2,
        ),
    }


_AUTHORING_RETRY_CODES = {
    "invalid_adoption",
    "invalid_adoption_projection",
    "incomplete_adoption_coverage",
    "usage",
}


def _governance_author(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo()
    cwd = _task_worktree(repo, args.task_id)
    draft_path = receipts.task_root(repo, args.task_id) / "governance-adoption.draft.yml"
    if not draft_path.is_file():
        raise AgentInvocationError(
            f"task '{args.task_id}' has no adoption draft to author",
            code="missing_adoption_draft",
        )
    draft = load_yaml(draft_path)
    if not isinstance(draft, dict):
        raise AgentInvocationError(
            "Invariant wrote an invalid adoption draft", code="invalid_invariant_output"
        )
    audit_id = str(draft.get("audit") or "")
    mappings = [item for item in draft.get("mappings", []) if isinstance(item, dict)]
    resolved = [item for item in mappings if not item.get("unresolved")]
    unresolved = sorted(
        {
            str(finding)
            for item in mappings
            if item.get("unresolved")
            for finding in item.get("findings", [])
        }
    )
    audit_raw = load_yaml(cwd / ".invariant" / "audits" / f"{audit_id}.yml")
    findings = [
        item
        for item in (audit_raw.get("findings", []) if isinstance(audit_raw, dict) else [])
        if isinstance(item, dict) and str(item.get("id")) in unresolved
    ]
    request = {
        "task": args.task_id,
        "authority": f"agent:{args.using.value}",
        "audit": audit_id,
        "findings": findings,
        "already_projected": resolved,
        "record_shapes": projected_record_schema(),
        "instructions": (
            "Each listed finding was selected for recording but carries no complete record "
            "projection. For each one, either author complete domain, contract, constraint, "
            "or semantic records grounded in its evidence and the repository, or defer it with "
            "the reason it cannot be recorded yet. Use only existing files and Markdown heading "
            "anchors for architecture and authority locators. Do not restate mappings that are "
            "already projected."
        ),
    }
    prompt = _prompt("governance.author", request)
    preview = _preview(
        args.using,
        args.task_id,
        "governance.author",
        cwd,
        "invariant://schemas/governance-authoring/v1",
        prompt,
    )
    if not args.apply:
        return preview
    if not unresolved:
        with tempfile.TemporaryDirectory(prefix="invariant-agent-response.") as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
            invariant = _invariant(
                repo, "governance", "project", args.task_id, "--input", str(manifest)
            )
        return {**preview, "applied": True, "usage": {}, "invariant": invariant}
    if args.timeout <= 0:
        raise AgentInvocationError("timeout must be greater than zero", code="invalid_invocation")
    current_prompt = prompt
    usage: dict[str, Any] = {}
    retries = 2
    for attempt in range(retries + 1):
        agent = invoke(
            args.using, cwd, current_prompt, authoring_schema(), model=args.model, timeout=args.timeout
        )
        for name, value in agent.usage.items():
            prior = usage.get(name)
            usage[name] = (
                prior + value
                if isinstance(prior, (int, float)) and isinstance(value, (int, float))
                else value
            )
        authored = [
            {name: value for name, value in item.items() if value not in (None, [], "")}
            for item in agent.response.get("mappings", [])
            if isinstance(item, dict)
            and any(str(finding) in unresolved for finding in item.get("findings", []))
        ]
        manifest_value = {"version": 1, "audit": audit_id, "mappings": [*resolved, *authored]}
        with tempfile.TemporaryDirectory(prefix="invariant-agent-response.") as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps(manifest_value, ensure_ascii=False), encoding="utf-8")
            try:
                invariant = _invariant(
                    repo, "governance", "project", args.task_id, "--input", str(manifest)
                )
            except AgentInvocationError as exc:
                if attempt >= retries or exc.code not in _AUTHORING_RETRY_CODES:
                    raise
                prior_response = json.dumps(
                    agent.response, sort_keys=True, indent=2, ensure_ascii=False
                )
                current_prompt = (
                    f"{prompt}\n\n"
                    "<invariant-validation-retry>\n"
                    "Invariant rejected the previous structured response. Correct only the "
                    "reported defect, then return the complete JSON object again. Cover every "
                    "listed finding; do not weaken, omit, or invent evidence.\n"
                    f"Rejection: {exc.message}\n"
                    f"Previous response:\n{prior_response}\n"
                    "</invariant-validation-retry>\n"
                )
                continue
        return {**preview, "applied": True, "usage": usage, "invariant": invariant}
    raise AgentInvocationError(
        "the agent did not complete the adoption draft", code="invalid_adoption"
    )


def _bound_action_schema(
    raw: dict[str, Any],
    action: dict[str, Any],
    provider: AgentProvider,
    review_mode: str = "self-attested",
) -> dict[str, Any]:
    schema = copy.deepcopy(raw)
    properties = schema.get("properties")
    context = action.get("context")
    if not isinstance(properties, dict):
        return schema
    if not isinstance(context, dict):
        context = {}
    for name in (
        "goal_digest",
        "source_goal_digest",
        "brief_digest",
        "candidate_tree",
        "review_id",
    ):
        if name in properties and context.get(name) is not None:
            value = properties[name]
            if isinstance(value, dict):
                value["const"] = context[name]
    authority = properties.get("authority")
    if isinstance(authority, dict):
        authority["const"] = f"agent:{provider.value}"
    mode = properties.get("review_mode")
    if isinstance(mode, dict):
        mode["const"] = review_mode
    return schema


def _action_for_response(
    repo: Path,
    task_id: str,
    action_id: str | None,
    provider: AgentProvider,
) -> tuple[str, dict[str, Any]]:
    try:
        task = _result(_invariant(repo, "task", "status", task_id), "task")
    except AgentInvocationError as exc:
        if exc.code == "missing_task":
            example = json.dumps(task_id, ensure_ascii=False)
            raise AgentInvocationError(
                f"no active Invariant task '{task_id}'. If {example} is a prompt, run: "
                f"invariant-agent ask --using {provider.value} {example}",
                code="missing_task",
                exit_code=exc.exit_code,
            ) from exc
        raise
    if not isinstance(task, dict):
        raise AgentInvocationError(
            "Invariant returned an invalid task", code="invalid_invariant_output"
        )
    actions = task.get("actions")
    if not isinstance(actions, list):
        raise AgentInvocationError(
            "Invariant task omitted its pending actions", code="invalid_invariant_output"
        )
    available = [
        str(item.get("id"))
        for item in actions
        if isinstance(item, dict) and item.get("id")
    ]
    selected = action_id
    if selected is None:
        if not available:
            stage = str(task.get("stage") or "unknown")
            raise AgentInvocationError(
                f"task '{task_id}' has no pending action (status: {stage})",
                code="no_pending_action",
            )
        if len(available) > 1:
            choices = ", ".join(available)
            raise AgentInvocationError(
                f"task '{task_id}' has multiple pending actions: {choices}. "
                "Choose one with --action ACTION_ID",
                code="ambiguous_action",
            )
        selected = available[0]
    action = _result(
        _invariant(repo, "task", "action", task_id, selected), "action"
    )
    if not isinstance(action, dict):
        raise AgentInvocationError(
            "Invariant returned an invalid action", code="invalid_invariant_output"
        )
    return selected, action


def _task_respond(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo()
    action_id, action = _action_for_response(
        repo, args.task_id, args.action_id, args.using
    )
    cwd = _task_worktree(repo, args.task_id)
    raw_schema = action.get("input_schema")
    if not isinstance(raw_schema, dict):
        raise AgentInvocationError(
            "Invariant action omitted its input schema", code="invalid_invariant_output"
        )
    context = action.get("context")
    evidence: list[Any] = []
    if isinstance(context, dict) and isinstance(context.get("evidence_ids"), list):
        for evidence_id in context["evidence_ids"]:
            evidence.append(
                _result(
                    _invariant(
                        repo,
                        "task",
                        "evidence",
                        args.task_id,
                        str(evidence_id),
                    ),
                    "evidence",
                )
            )
    review_mode = "independent" if getattr(args, "independent", False) else "self-attested"
    attribution = {"authority": f"agent:{args.using.value}", "review_mode": review_mode}
    schema = _bound_action_schema(raw_schema, action, args.using, review_mode)
    request = {
        "task": args.task_id,
        "action": action,
        "evidence": evidence,
        "attribution": attribution,
    }
    prompt = _prompt("task.respond", request)
    preview = _preview(
        args.using,
        args.task_id,
        f"task.respond:{action_id}",
        cwd,
        str(action.get("schema_id") or "embedded"),
        prompt,
    )
    if not args.apply:
        return preview
    return {
        **preview,
        **_invoke_and_submit(
            repo,
            args.using,
            cwd,
            prompt,
            schema,
            ("task", "respond", args.task_id, action_id),
            model=args.model,
            timeout=args.timeout,
            stamps=attribution,
        ),
    }


def _text(payload: dict[str, Any]) -> str:
    if "providers" in payload:
        lines = []
        for item in payload["providers"]:
            availability = "available" if item["available"] else "missing"
            suffix = f" — {item['version']}" if item["version"] else ""
            lines.append(f"AGENT: {item['provider']} — {availability}{suffix}")
            if item["executable"]:
                lines.append(f"EXECUTABLE: {item['provider']} — {item['executable']}")
            if item["hint"]:
                lines.append(f"NEXT: {item['provider']} — {item['hint']}")
        return "\n".join(lines)
    if isinstance(payload.get("message"), str):
        return payload["message"]
    lines = [
        f"AGENT: {payload.get('provider')}",
        f"OPERATION: {payload.get('operation')}",
        "MODE: read-only",
        (
            f"REPOSITORY: {payload.get('cwd')}"
            if payload.get("operation") == "ask"
            else f"WORKTREE: {payload.get('cwd')}"
        ),
        f"SCHEMA: {payload.get('schema')}",
        f"PROMPT-DIGEST: {payload.get('prompt_digest')}",
    ]
    if payload.get("applied"):
        if payload.get("session_id"):
            lines.append(f"SESSION: {payload['session_id']}")
        lines.extend(
            [
                f"RESPONSE-DIGEST: {payload.get('response_digest')}",
                "STATUS: submitted",
            ]
        )
    else:
        next_step = (
            "rerun without --dry-run to invoke the agent"
            if payload.get("operation") == "ask"
            else "rerun with --apply to invoke the agent"
        )
        lines.extend(["STATUS: preview", f"NEXT: {next_step}"])
    return "\n".join(lines)


def _envelope(
    command: str, status: str, outcome: str, result: dict[str, Any], diagnostics: list[dict[str, str]]
) -> str:
    return json.dumps(
        {
            "protocol": 1,
            "command": command,
            "status": status,
            "outcome": outcome,
            "result": result,
            "diagnostics": diagnostics,
        },
        separators=(",", ":"),
    )


def run(argv: list[str] | None = None) -> int:
    command = "agent"
    values = hoist_global_options(
        sys.argv[1:] if argv is None else argv, valued=("--format",), flags=()
    )
    format_name = "json" if requested_format(values) == "json" else "text"
    try:
        args = build_parser().parse_args(values)
        format_name = args.format
        command = str(getattr(args, "command_name", command))
        payload = args.handler(args)
        if format_name == "json":
            print(_envelope(command, "ok", "completed", payload, []))
        else:
            print(_text(payload))
        return 0
    except AgentInvocationError as exc:
        return _fail(command, format_name, exc.message, exc.code, exc.exit_code)
    except Exception as exc:  # keep the envelope contract even for unexpected failures
        traceback.print_exc(file=sys.stderr)
        detail = str(exc).strip()
        message = f"internal failure — {type(exc).__name__}{': ' + detail if detail else ''}"
        return _fail(command, format_name, message, "internal_error", 2)


def _fail(command: str, format_name: str, message: str, code: str, exit_code: int) -> int:
    if format_name == "json":
        blocked = exit_code == 1
        print(
            _envelope(
                command,
                "blocked" if blocked else "error",
                "blocked" if blocked else "failed",
                {},
                [{"code": code, "message": message}],
            )
        )
    else:
        print(f"Invariant agent: {message}", file=sys.stderr)
    return exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
