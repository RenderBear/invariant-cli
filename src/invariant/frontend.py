from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from invariant import __version__
from invariant.cli import app as protocol_cli
from invariant.cli import style
from invariant.cli.argv import hoist_global_options, requested_format
from invariant.cli.commands import initialize as initialize_command
from invariant.cli.output import CommandResult, emit_error, emit_success, internal_error
from invariant.errors import Blocked, InvariantError, UsageError
from invariant.harness import cli as harness_cli
from invariant.harness.providers import (
    AgentInvocationError,
    AgentProvider,
    AgentWriteResult,
    connect,
    connection_status,
    invoke,
    invoke_change,
    invoke_session,
)
from invariant.harness import preferences
from invariant.lifecycle import bootstrap
from invariant.mechanics import config, coordinate, git, receipts
from invariant.mechanics import governance
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.semantics import sources
from invariant.semantics.namespaces import Locator, parse_source_scope


PUBLIC_COMMANDS = {
    "ask",
    "change",
    "connect",
    "establish",
    "help",
    "init",
    "set",
    "settings",
    "source",
    "start",
    "status",
}


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(f"Invariant: {message}")


def _provider(value: str) -> AgentProvider:
    try:
        return AgentProvider(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use codex or claude") from None


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="invariant",
        description=(
            "Scale agentic coding without architectural drift. Keep accepted architecture "
            "durable while coding agents plan, edit, verify, and land local changes."
        ),
        epilog=(
            "Bring an existing Codex or Claude sign-in; add grounding sources and intent "
            "review only when useful. Low-level protocol commands remain available for automation. "
            "Run 'invariant help protocol' to see them."
        ),
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="include diagnostic detail (or complete text in JSON responses)",
    )
    parser.add_argument("--version", action="version", version=f"invariant {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    initialize = commands.add_parser(
        "init", help="set up this repository"
    )
    initialize.add_argument(
        "--defaults",
        action="store_true",
        help="use safe defaults instead of choosing repository policy",
    )
    initialize.add_argument(
        "--agent", choices=["auto", "codex", "claude"], help="repository agent"
    )
    initialize.set_defaults(handler=_init)

    connection = commands.add_parser(
        "connect", help="use an existing Codex or Claude sign-in"
    )
    connection.add_argument("provider", nargs="?", type=_provider)
    connection.add_argument(
        "--default",
        dest="default_provider",
        type=_provider,
        metavar="codex|claude",
        help="connect and make this the machine's default harness",
    )
    connection.set_defaults(handler=_connect)

    ask = commands.add_parser(
        "ask", help="ask a read-only repository question"
    )
    _invocation_arguments(ask, timeout=600)
    ask.add_argument(
        "--dry-run", action="store_true", help="preview without invoking the agent"
    )
    ask.add_argument("prompt")
    ask.set_defaults(handler=_ask)

    start = commands.add_parser(
        "start", help="start a persistent repository conversation"
    )
    _invocation_arguments(start, timeout=600)
    start.add_argument(
        "--mode",
        choices=["ask", "change"],
        help="override the repository's default session mode",
    )
    start.add_argument("prompt", nargs="?", help="optional first message")
    start.set_defaults(handler=_start)

    change = commands.add_parser(
        "change", help="implement, check, and land one managed change"
    )
    _invocation_arguments(change, timeout=1800)
    change.add_argument("--id", dest="change_id", help="stable change ID for automation")
    change.add_argument("--boundary", default="unresolved", help=argparse.SUPPRESS)
    change.add_argument("--path", action="append", default=[], help=argparse.SUPPRESS)
    change.add_argument("--interface", action="append", default=[], help=argparse.SUPPRESS)
    change.add_argument("--domain", action="append", default=[], help=argparse.SUPPRESS)
    change.add_argument("--dry-run", action="store_true", help="preview without creating state")
    change.add_argument("prompt")
    change.set_defaults(handler=_change)

    establish = commands.add_parser(
        "establish", help="establish or refresh durable repository records"
    )
    _invocation_arguments(establish, timeout=1800)
    establish.add_argument(
        "--id", dest="change_id", help="stable establishment ID for automation"
    )
    establish.add_argument("--goal", help="optional focus for repository establishment")
    establish.add_argument(
        "--dry-run", action="store_true", help="preview without creating state"
    )
    establish.set_defaults(handler=_establish)

    status_parser = commands.add_parser(
        "status", help="show repository state and the next useful operation"
    )
    status_parser.add_argument("change_id", nargs="?")
    status_parser.set_defaults(handler=_status)

    settings = commands.add_parser("settings", help="show repository settings")
    settings.set_defaults(handler=_settings)

    setting = commands.add_parser("set", help="set one repository preference")
    setting.add_argument("key")
    setting.add_argument("value")
    setting.set_defaults(handler=_set)

    source = commands.add_parser(
        "source", help="add an optional grounding source"
    )
    source_commands = source.add_subparsers(
        dest="source_command", required=True, parser_class=Parser
    )
    source_add = source_commands.add_parser(
        "add", help="add one URL or .invariant-relative source"
    )
    _source_add_arguments(source_add)
    source_add.set_defaults(handler=_source_add, session_provider=None)

    help_parser = commands.add_parser("help", help="show help for a command surface")
    help_parser.add_argument("surface", nargs="?", choices=["protocol"])
    help_parser.set_defaults(handler=_help)
    return parser


def _invocation_arguments(parser: argparse.ArgumentParser, *, timeout: int) -> None:
    parser.add_argument("--using", type=_provider, metavar="codex|claude")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=timeout)


def _source_add_arguments(parser: argparse.ArgumentParser) -> None:
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument("--url")
    origin.add_argument(
        "--path", help="existing file beneath .invariant/sources, relative to .invariant"
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--scope", help="domain:<id>, contract:<id>, or a natural-language description"
    )
    scope.add_argument(
        "--repo",
        dest="repository_scope",
        action="store_true",
        help="apply throughout this repository",
    )


def _top_level_command(argv: list[str]) -> str | None:
    skip = False
    for value in argv:
        if skip:
            skip = False
            continue
        if value == "--format":
            skip = True
            continue
        if value.startswith("--format=") or value in {
            "--verbose",
            "--version",
            "-h",
            "--help",
        }:
            continue
        if value.startswith("-"):
            continue
        return value
    return None


def _agent_error(error: AgentInvocationError) -> InvariantError:
    message = f"Invariant: {error.message}"
    if error.exit_code == 1:
        return Blocked(message, code=error.code)
    return InvariantError(message, code=error.code, exit_code=2)


def _identify(error: InvariantError, label: str, identifier: str) -> InvariantError:
    prefix = f"{label}: {identifier}"
    if prefix not in error.lines:
        error.lines.insert(0, prefix)
    return error


def _core(repo: Path, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-P", "-m", "invariant.cli.app", "--format", "json", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = (completed.stderr or completed.stdout).strip()
        raise InvariantError(
            f"Invariant: internal protocol returned invalid JSON{': ' + detail if detail else ''}",
            code="invalid_protocol_output",
        ) from exc
    if not isinstance(payload, dict):
        raise InvariantError(
            "Invariant: internal protocol returned a non-object response",
            code="invalid_protocol_output",
        )
    if completed.returncode:
        diagnostics = payload.get("diagnostics")
        diagnostic = (
            diagnostics[0]
            if isinstance(diagnostics, list) and diagnostics and isinstance(diagnostics[0], dict)
            else {}
        )
        message = str(diagnostic.get("message") or "Invariant protocol operation failed")
        code = str(diagnostic.get("code") or "protocol_operation_failed")
        result = payload.get("result")
        records = result.get("records") if isinstance(result, dict) else None
        lines = [
            f"{item.get('name')}: {item.get('value')}"
            for item in records or []
            if isinstance(item, dict) and item.get("name")
        ]
        error_type = Blocked if completed.returncode == 1 else InvariantError
        raise error_type(message, code=code, lines=lines)
    return payload


def _result(payload: dict[str, Any], name: str) -> Any:
    result = payload.get("result")
    if not isinstance(result, dict) or name not in result:
        raise InvariantError(
            f"Invariant: internal protocol omitted result.{name}",
            code="invalid_protocol_output",
        )
    return result[name]


def _connection_payload(provider: AgentProvider) -> dict[str, Any]:
    state = connection_status(provider)
    return {
        "provider": provider.value,
        "installed": state.installed,
        "authenticated": state.authenticated,
        "connected": state.installed and state.authenticated,
        "executable": state.executable,
        "version": state.version,
        "hint": state.hint,
    }


def _connection_label(item: dict[str, Any]) -> str:
    return (
        "connected"
        if item["connected"]
        else "sign-in needed"
        if item["installed"]
        else "not installed"
    )


def _connection_lines(
    values: list[dict[str, Any]],
    *,
    preferred_provider: AgentProvider | None = None,
    preference_label: str = "default",
) -> list[str]:
    default = preferred_provider or preferences.default_harness()
    preferred = next(
        (item for item in values if item.get("provider") == default.value), None
    )
    primary = (
        preferred
        if preferred and preferred.get("connected")
        else next((item for item in values if item.get("connected")), None)
        or preferred
        or (values[0] if values else None)
    )
    if primary is None:
        return []

    version = f" · {primary['version']}" if primary["version"] else ""
    qualifier = (
        f" · {preference_label}"
        if primary["provider"] == default.value
        else " · automatic fallback"
    )
    primary_name = _provider_name(AgentProvider(str(primary["provider"])))
    lines = [f"AGENT: {primary_name} — {_connection_label(primary)}{version}{qualifier}"]
    for item in values:
        if item is primary:
            continue
        version = f" · {item['version']}" if item["version"] else ""
        qualifier = (
            f" · {preference_label}" if item["provider"] == default.value else ""
        )
        kind = "AVAILABLE" if item["connected"] else "OPTIONAL"
        provider_name = _provider_name(AgentProvider(str(item["provider"])))
        lines.append(
            f"{kind}: {provider_name} — {_connection_label(item)}{version}{qualifier}"
        )
    if not any(item["connected"] for item in values) and primary.get("hint"):
        lines.append(f"NEXT: {primary['hint']}")
    return lines


def _connect(args: argparse.Namespace) -> CommandResult:
    if (
        args.provider is not None
        and args.default_provider is not None
        and args.provider != args.default_provider
    ):
        raise UsageError(
            "Invariant: the connected provider and --default harness must match"
        )
    selected = args.default_provider or args.provider
    if selected is not None:
        try:
            connect(selected)
        except AgentInvocationError as exc:
            raise _agent_error(exc) from exc
    if args.default_provider is not None:
        preferences.set_default_harness(args.default_provider)
    values = [_connection_payload(provider) for provider in AgentProvider]
    default = preferences.default_harness()
    lines: list[str] = []
    if selected is not None:
        lines.append(f"CONNECTED: {selected.value}")
    lines.extend(_connection_lines(values))
    return CommandResult(
        lines,
        {
            "default_harness": default.value,
            "connections": values,
        },
    )


def _resolve_provider(repo: Path, requested: AgentProvider | None) -> AgentProvider:
    configured = preferences.repo_harness(repo)
    candidates = (
        [requested] if requested is not None else preferences.harness_candidates(repo)
    )
    for provider in candidates:
        state = connection_status(provider)
        if state.installed and state.authenticated:
            return provider
    if requested is not None or configured != "auto":
        provider = requested or AgentProvider(configured)
        raise InvariantError(
            f"Invariant: {provider.value} is not connected; "
            f"run 'invariant connect {provider.value}'",
            code="agent_not_connected",
        )
    raise InvariantError(
        "Invariant: no coding agent is connected; run 'invariant connect codex' or "
        "'invariant connect claude'",
        code="agent_not_connected",
    )


def _provider_name(provider: AgentProvider) -> str:
    return "Codex" if provider == AgentProvider.CODEX else "Claude Code"


def _connect_for_initialization(
    requested: str,
) -> tuple[AgentProvider | None, list[dict[str, Any]], list[str]]:
    default = preferences.default_harness()
    candidates = (
        [AgentProvider(requested)]
        if requested != "auto"
        else [default, *[provider for provider in AgentProvider if provider != default]]
    )
    attempts: list[dict[str, Any]] = []
    warnings: list[str] = []
    for provider in candidates:
        try:
            connect(provider)
        except AgentInvocationError as exc:
            attempts.append(_connection_payload(provider))
            warnings.append(
                f"WARNING: {_provider_name(provider)} connection failed — {exc.message}; skipped"
            )
            continue
        state = _connection_payload(provider)
        attempts.append(state)
        if state["connected"]:
            return provider, attempts, warnings
        warnings.append(
            f"WARNING: {_provider_name(provider)} connection could not be verified; skipped"
        )
    return None, attempts, warnings


def _init(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    if args.format == "json" and not args.defaults:
        raise UsageError("Invariant: JSON initialization requires --defaults")
    replacing = False
    if config.initialized(repo):
        existing = config.resolve(repo)
        if args.format == "json":
            raise UsageError(
                "Invariant: configuration already exists; use 'invariant set <key> <value>' "
                "for one setting or run text-mode 'invariant init' to replace it"
            )
        replacing = initialize_command.replacement_choice()
        if not replacing:
            return CommandResult(
                [
                    "STATUS: unchanged",
                    "NEXT: use 'invariant set <key> <value>' to change one setting",
                ],
                {
                    "initialization": {"replaced": False},
                    "agent": preferences.repo_harness(repo),
                    "connections": [],
                    "setup_commit": "",
                    "establishment": {},
                },
            )
    existing_changes = git.changed_paths(repo)
    settings = initialize_command.settings(
        repo,
        defaults=args.defaults,
        show_logo=not replacing and args.format == "text",
    )
    # The provider choice is a fact about this clone and machine, so it never enters the
    # tracked configuration that the setup commit records.
    if args.agent:
        preferences.set_repo_harness(repo, args.agent)
    configured = preferences.repo_harness(repo)
    connected, attempts, warning_lines = _connect_for_initialization(configured)
    selected_provider = connected or preferences.effective_harness(repo)
    initialization_lines = bootstrap.initialize(repo, settings, overwrite=replacing)
    setup_commit = ""
    setup_paths = git.changed_paths(repo)
    if not existing_changes and setup_paths:
        git.run(["add", "--", *setup_paths], cwd=repo)
        git.run(
            [
                "commit",
                "-q",
                "-m",
                "Reconfigure Invariant" if replacing else "Initialize Invariant",
                "-m",
                "Invariant-Unit: initialization\n"
                "Invariant-Scope: area.root\n"
                "Invariant-Boundary: no-record",
            ],
            cwd=repo,
        )
        setup_commit = git.resolve(repo, "HEAD") or ""
    lines: list[str] = []
    lines.extend(warning_lines)
    chosen_state = next(
        (item for item in attempts if item["provider"] == selected_provider.value),
        _connection_payload(selected_provider),
    )
    lines.extend(
        line
        for line in _connection_lines(
            [chosen_state],
            preferred_provider=selected_provider,
            preference_label="repository agent",
        )
        if not line.startswith("NEXT:")
    )
    resolved = config.resolve(repo)
    authority = "Agent decides" if resolved.authority == "agent" else "Ask me"
    execution = "automatic" if resolved.execution == "auto" else "confirm transitions"
    landing = resolved.integration_branch
    if resolved.integration_branch_setting == "auto":
        landing = f"{landing} (current)"
    publishing = "local only" if resolved.push_remote == "off" else "publish upstream"
    requests = (
        "Intent brief" if resolved.adapters.is_enabled("intent_brief") else "Direct"
    )
    lines.extend(
        [
            f"POLICY: {authority} · {execution}",
            f"LANDING: {landing} · {publishing}",
            f"REQUESTS: {requests}",
        ]
    )
    if setup_commit:
        lines.append(f"SETUP-COMMIT: {setup_commit}")
    elif existing_changes:
        lines.append("SETUP-COMMIT: not created — repository has existing changes")
    offer_establishment = args.format == "text" and (
        not args.defaults or sys.stdin.isatty()
    )
    establish_now = (
        initialize_command.establishment_choice() if offer_establishment else False
    )

    establishment_result: dict[str, Any] = {}
    if establish_now and existing_changes:
        lines.append(
            "ESTABLISH: waiting — commit the initialization, then run 'invariant establish'"
        )
        connection_step = (
            f", connect {selected_provider.value}"
            if connected is None
            else ""
        )
        lines.append(
            f"NEXT: review and commit the initialization{connection_step}, then run 'invariant establish'"
        )
    elif establish_now and connected is None:
        lines.append("ESTABLISH: skipped — no coding agent connected")
        lines.append(
            f"NEXT: run 'invariant connect {selected_provider.value}', then 'invariant establish'"
        )
    elif establish_now:
        established = _establish(
            argparse.Namespace(
                using=None,
                model=None,
                timeout=1800,
                change_id=None,
                goal=None,
                dry_run=False,
            )
        )
        lines.extend(established.lines)
        if isinstance(established.data, dict):
            establishment_result = established.data
    elif existing_changes:
        connection_step = (
            f", connect {selected_provider.value}"
            if connected is None
            else ""
        )
        lines.append(
            f"NEXT: review and commit the initialization{connection_step}, then run 'invariant establish'"
        )
    elif connected is None:
        lines.append(
            f"NEXT: run 'invariant connect {selected_provider.value}', then 'invariant establish'"
        )
    else:
        lines.append("NEXT: run 'invariant establish' when you are ready to establish records")
    return CommandResult(
        lines,
        {
            "initialization": {
                "records": [
                    {"name": name, "value": value}
                    for line in initialization_lines
                    for name, separator, value in [line.partition(": ")]
                    if separator
                ]
            },
            "agent": configured,
            "connections": attempts,
            "setup_commit": setup_commit,
            "establishment": establishment_result,
        },
    )


def _grounding_prompt(repo: Path) -> str:
    context = sources.prompt_context(repo)
    return f"\n\n{context}" if context else ""


def _question_prompt(repo: Path, question: str) -> str:
    return (
        "You are answering a read-only repository question through Invariant. Inspect the "
        "current repository when useful. Do not modify files, create commits, or change external "
        "state. Return exactly one JSON object matching the supplied schema.\n\n"
        f"Question:\n{question.strip()}\n"
        f"{_grounding_prompt(repo)}"
    )


def _ask(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    if not args.prompt.strip():
        raise UsageError("Invariant: prompt cannot be empty")
    provider = _resolve_provider(repo, args.using)
    preview = {
        "provider": provider.value,
        "operation": "ask",
        "mode": "read-only",
        "repository": str(repo),
        "invoked": False,
    }
    if args.dry_run:
        return CommandResult(
            [
                f"AGENT: {provider.value}",
                "MODE: read-only",
                f"REPOSITORY: {repo}",
                "STATUS: preview",
            ],
            preview,
        )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["message"],
        "properties": {"message": {"type": "string", "minLength": 1}},
    }
    if args.format == "text" and style.interactive():
        print(f"{style.user_line(args.prompt.strip(), 'ask')}\n")
    started = time.monotonic()
    turn = style.turn(provider.value)
    try:
        with turn:
            result = invoke(
                provider,
                repo,
                _question_prompt(repo, args.prompt),
                schema,
                model=args.model,
                timeout=args.timeout,
            )
    except AgentInvocationError as exc:
        raise _agent_error(exc) from exc
    message = result.response.get("message")
    if not isinstance(message, str) or not message:
        raise InvariantError(
            f"Invariant: {provider.value} omitted its answer", code="invalid_agent_output"
        )
    return CommandResult(
        [message],
        {
            **preview,
            "invoked": True,
            "prompt": args.prompt,
            "message": message,
            "session_id": result.session_id,
            "usage": result.usage,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "heading_shown": turn.rendered,
        },
    )


@dataclass
class _ConsoleSession:
    identifier: int
    mode: str
    provider_session_id: str = ""


def _session_schema(mode: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "message": {"type": "string", "minLength": 1}
    }
    required = ["message"]
    if mode == "change":
        properties["action"] = {"type": "string", "enum": ["answer", "change"]}
        required.insert(0, "action")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _session_prompt(repo: Path, mode: str, message: str) -> str:
    if mode == "ask":
        instruction = (
            "Answer the user's repository question. This is a persistent conversation, so use "
            "relevant context from earlier turns."
        )
    else:
        instruction = (
            "Act as a read-only coordinator. Choose action=answer for questions, explanation, "
            "or exploration. Choose action=change only when the user asks to modify repository "
            "state. For a change, message must be a self-contained implementation request for "
            "Invariant's managed change lifecycle. For an answer, message is the answer."
        )
    return (
        "You are working through an Invariant repository session. Inspect the repository when "
        "useful, but do not modify files, create commits, or change external state in this "
        "conversation. Return exactly one JSON object matching the supplied schema.\n\n"
        f"Session mode: {mode}\n{instruction}\n\nUser message:\n{message.strip()}\n"
        f"{_grounding_prompt(repo)}"
    )


def _show(title: str, lines: list[str], *, critical: bool = False) -> None:
    rendered = style.panel(
        title,
        lines,
        tone=style.BAD if critical else None,
        branded=False,
    )
    if rendered:
        print(rendered)


def _show_agent(
    provider: AgentProvider,
    message: str,
    *,
    heading: bool = True,
) -> None:
    rendered = style.agent_message(provider.value, message, heading=heading)
    if rendered:
        print(rendered)


def _session_turn(
    repo: Path,
    provider: AgentProvider,
    session: _ConsoleSession,
    message: str,
    *,
    model: str | None,
    timeout: int,
) -> None:
    turn = style.turn(provider.value)
    try:
        with turn:
            result = invoke_session(
                provider,
                repo,
                _session_prompt(repo, session.mode, message),
                _session_schema(session.mode),
                session_id=session.provider_session_id or None,
                model=model,
                timeout=timeout,
            )
    except AgentInvocationError as exc:
        raise _agent_error(exc) from exc
    session.provider_session_id = result.session_id
    response = result.response.get("message")
    if not isinstance(response, str) or not response.strip():
        raise InvariantError(
            f"Invariant: {provider.value} omitted its session response",
            code="invalid_agent_output",
        )
    if session.mode == "ask" or result.response.get("action") == "answer":
        _show_agent(provider, response.strip(), heading=not turn.rendered)
        return
    if result.response.get("action") != "change":
        raise InvariantError(
            f"Invariant: {provider.value} returned an invalid session action",
            code="invalid_agent_output",
        )
    _show_agent(provider, response.strip(), heading=not turn.rendered)
    changed = _change(
        argparse.Namespace(
            using=provider,
            model=model,
            timeout=max(timeout, 1800),
            change_id=None,
            boundary="unresolved",
            path=[],
            interface=[],
            domain=[],
            dry_run=False,
            prompt=response.strip(),
        )
    )
    rendered = style.render("change", changed.lines, branded=False)
    if rendered:
        print(rendered)


def _session_list(
    sessions: list[_ConsoleSession], active: _ConsoleSession, provider: AgentProvider
) -> None:
    lines = [
        "SESSION: {identifier} — {state} — {mode} — {context}".format(
            identifier=session.identifier,
            state="active" if session is active else "available",
            mode=session.mode,
            context=(
                f"{provider.value} context ready"
                if session.provider_session_id
                else "no messages yet"
            ),
        )
        for session in sessions
    ]
    _show("Sessions", lines)


def _start(args: argparse.Namespace) -> CommandResult:
    if args.format == "json":
        raise UsageError("Invariant: start is an interactive text command")
    repo = git.root()
    provider = _resolve_provider(repo, args.using)
    default_mode = args.mode or preferences.session_mode(repo)
    sessions = [_ConsoleSession(1, default_mode)]
    active = sessions[0]
    pending = args.prompt.strip() if isinstance(args.prompt, str) else ""
    print(style.session_intro(provider.value, active.mode, active.identifier))
    try:
        while True:
            if pending:
                message = pending
                pending = ""
            elif sys.stdin.isatty():
                message = input(style.prompt(active.mode)).strip()
                redrawn = style.redraw_user_line(message, active.mode) if message else None
                if redrawn:
                    print(redrawn)
            else:
                raw = sys.stdin.readline()
                if raw == "":
                    break
                message = raw.strip()
            if not message:
                continue
            if not message.startswith(":") and sys.stdin.isatty() and sys.stdout.isatty():
                print()
            if message.startswith(":"):
                command, _, value = message[1:].partition(" ")
                command = command.strip().lower()
                value = value.strip()
                if command in {"exit", "quit"}:
                    break
                if command == "help":
                    _show(
                        "Session commands",
                        [
                            "COMMAND: :mode ask|change — switch this session",
                            "COMMAND: :new [message] — open and switch to a new session",
                            "COMMAND: :sessions — list sessions in this console",
                            "COMMAND: :switch N — return to a listed session",
                            "COMMAND: :status — show deterministic repository status",
                            "COMMAND: :settings — show repository settings",
                            "COMMAND: :set KEY VALUE — update one repository preference",
                            "COMMAND: :source add --url URL|--path PATH --scope SCOPE|--repo",
                            "COMMAND: :exit — end this console",
                        ],
                    )
                    continue
                if command == "mode":
                    if value not in {"ask", "change"}:
                        _show("Session", ["USAGE: :mode ask|change"])
                        continue
                    active.mode = value
                    _show(
                        "Session",
                        [f"SESSION: {active.identifier}", f"MODE: {active.mode}"],
                    )
                    continue
                if command == "new":
                    active = _ConsoleSession(len(sessions) + 1, active.mode)
                    sessions.append(active)
                    _show(
                        "Session",
                        [f"SESSION: {active.identifier}", f"MODE: {active.mode}"],
                    )
                    pending = value
                    continue
                if command == "sessions":
                    _session_list(sessions, active, provider)
                    continue
                if command == "switch":
                    try:
                        identifier = int(value)
                    except ValueError:
                        identifier = 0
                    selected = next(
                        (
                            session
                            for session in sessions
                            if session.identifier == identifier
                        ),
                        None,
                    )
                    if selected is None:
                        _show("Session", ["USAGE: :switch N — use :sessions to list N"])
                        continue
                    active = selected
                    _show(
                        "Session",
                        [f"SESSION: {active.identifier}", f"MODE: {active.mode}"],
                    )
                    continue
                if command == "status":
                    if value:
                        _show("Session", ["USAGE: :status"])
                        continue
                    try:
                        result = _status(
                            argparse.Namespace(change_id=None, verbose=False)
                        )
                        rendered = style.render("status", result.lines, branded=False)
                        if rendered:
                            print(rendered)
                    except InvariantError as exc:
                        _show_session_error(exc)
                    continue
                if command == "settings":
                    if value:
                        _show("Session", ["USAGE: :settings"])
                        continue
                    try:
                        result = _settings(argparse.Namespace())
                        rendered = style.render("settings", result.lines, branded=False)
                        if rendered:
                            print(rendered)
                    except InvariantError as exc:
                        _show_session_error(exc)
                    continue
                if command == "set":
                    try:
                        values = shlex.split(value)
                    except ValueError as exc:
                        _show("Session", [f"INVALID: {exc}"])
                        continue
                    if len(values) != 2:
                        _show("Session", ["USAGE: :set KEY VALUE"])
                        continue
                    try:
                        result = _set(
                            argparse.Namespace(key=values[0], value=values[1])
                        )
                        if values[0] == "mode":
                            active.mode = values[1]
                        rendered = style.render("set", result.lines, branded=False)
                        if rendered:
                            print(rendered)
                    except InvariantError as exc:
                        _show_session_error(exc)
                    continue
                if command == "source":
                    try:
                        source_args = _parse_session_source(value)
                        source_args.session_provider = provider
                        source_args.model = args.model
                        source_args.timeout = args.timeout
                        result = _source_add(source_args)
                        rendered = style.render("source", result.lines, branded=False)
                        if rendered:
                            print(rendered)
                    except InvariantError as exc:
                        _show_session_error(exc)
                    continue
                _show("Session", [f"UNKNOWN: :{command} — use :help"])
                continue
            try:
                _session_turn(
                    repo,
                    provider,
                    active,
                    message,
                    model=args.model,
                    timeout=args.timeout,
                )
            except InvariantError as exc:
                if exc.lines:
                    _show("Stopped", exc.lines, critical=True)
                print(style.error(exc.message), file=sys.stderr)
            if sys.stdin.isatty() and sys.stdout.isatty():
                print(style.turn_separator())
    except (EOFError, KeyboardInterrupt):
        pass
    outro = style.session_outro()
    print(f"\n{outro}\n" if style.interactive() else outro)
    return CommandResult(
        [],
        {
            "provider": provider.value,
            "sessions": len(sessions),
            "mode": active.mode,
        },
    )


def _show_session_error(exc: InvariantError) -> None:
    if exc.lines:
        _show("Stopped", exc.lines, critical=True)
    print(style.error(exc.message), file=sys.stderr)
    if sys.stdin.isatty() and sys.stdout.isatty():
        print(file=sys.stderr)


def _parse_session_source(value: str) -> argparse.Namespace:
    parser = Parser(prog=":source")
    commands = parser.add_subparsers(
        dest="source_command", required=True, parser_class=Parser
    )
    addition = commands.add_parser("add")
    _source_add_arguments(addition)
    try:
        return parser.parse_args(shlex.split(value))
    except ValueError as exc:
        raise UsageError(f"Invariant: invalid source command: {exc}") from exc


def _scope_catalog(repo: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    domains = [
        {"id": item.identifier, "responsibility": item.responsibility}
        for item in governance.domains(repo)
    ]
    contracts = [
        {
            "id": str(item.get("id") or ""),
            "assertion": str(item.get("assertion") or ""),
        }
        for item in governance.contracts(repo)
        if item.get("id")
    ]
    return domains, contracts


def _require_existing_scope(repo: Path, locator: Locator) -> None:
    domains, contracts = _scope_catalog(repo)
    identifiers = {
        item["id"]
        for item in (domains if locator.namespace == "domain" else contracts)
    }
    if locator.identifier not in identifiers:
        raise Blocked(
            f"Invariant: source scope '{locator.value}' is not established",
            code="missing_source_scope",
            lines=[
                f"SCOPE: {locator.value}",
                "NEXT: run 'invariant establish' or choose an existing domain or contract",
            ],
        )


def _scope_resolution_prompt(
    description: str,
    domains: list[dict[str, str]],
    contracts: list[dict[str, str]],
) -> str:
    catalog = json.dumps(
        {"domains": domains, "contracts": contracts},
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "Resolve one user-written source scope to exactly one already accepted repository "
        "domain or contract. Use only the user's phrase and the supplied repository catalog. "
        "Do not retrieve or inspect the source being added, create a new semantic object, or "
        "treat third-party content as authority. Return exactly one JSON object matching the "
        "supplied schema.\n\n"
        f"User scope:\n{description.strip()}\n\nAccepted catalog:\n{catalog}\n"
    )


def _resolve_source_scope(
    repo: Path,
    value: str,
    *,
    provider: AgentProvider | None,
    model: str | None,
    timeout: int,
) -> tuple[str, str | None]:
    scope = value.strip()
    if not scope:
        raise UsageError("Invariant: --scope cannot be empty")
    if ":" in scope:
        locator = parse_source_scope(scope)
        _require_existing_scope(repo, locator)
        return locator.value, None

    domains, contracts = _scope_catalog(repo)
    if not domains and not contracts:
        raise Blocked(
            "Invariant: natural-language scope needs an established domain or contract",
            code="missing_source_scope",
            lines=["NEXT: run 'invariant establish' or use --repo"],
        )
    selected = provider or _resolve_provider(repo, None)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["namespace", "id"],
        "properties": {
            "namespace": {"type": "string", "enum": ["domain", "contract"]},
            "id": {"type": "string", "minLength": 1},
        },
    }
    try:
        result = invoke(
            selected,
            repo,
            _scope_resolution_prompt(scope, domains, contracts),
            schema,
            model=model,
            timeout=timeout,
        )
    except AgentInvocationError as exc:
        raise _agent_error(exc) from exc
    namespace = result.response.get("namespace")
    identifier = result.response.get("id")
    if not isinstance(namespace, str) or not isinstance(identifier, str):
        raise InvariantError(
            f"Invariant: {selected.value} returned an invalid source scope",
            code="invalid_agent_output",
        )
    locator = parse_source_scope(f"{namespace}:{identifier}")
    _require_existing_scope(repo, locator)
    return locator.value, scope


def _source_provider(repo: Path, requested: AgentProvider | None) -> AgentProvider:
    if requested is not None:
        return requested
    return preferences.effective_harness(repo)


def _source_domains(repo: Path, scope: str) -> list[str]:
    locator = parse_source_scope(scope)
    if locator.namespace == "domain":
        return [locator.identifier]
    row = next(
        (
            item
            for item in governance.contracts(repo)
            if str(item.get("id") or "") == locator.identifier
        ),
        {},
    )
    return sorted(set(governance.refs(row.get("between"))))


def _source_result(source: sources.Source, status: str, commit: str = "") -> CommandResult:
    scope = "repository" if source.scope == sources.REPOSITORY_SCOPE else source.scope
    lines = [
        f"SOURCE: {source.reference}",
        f"ORIGIN: {source.origin}",
        f"SCOPE: {scope}",
        f"STATUS: {status}",
    ]
    if commit:
        lines.append(f"COMMIT: {commit}")
    return CommandResult(
        lines,
        {"source": source.as_dict(), "status": status, "commit": commit},
    )


def _source_add(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    if not (repo / config.CONFIG_PATH).is_file():
        raise InvariantError(
            "Invariant: this repository is not initialized; run 'invariant init' first",
            code="not_initialized",
        )
    nested = git.tracked_nested_invariant_paths(repo)
    if nested:
        raise Blocked(
            "Invariant: this Git repository contains nested Invariant state",
            code="nested_invariant",
            lines=[f"NESTED: {path}" for path in nested]
            + ["NEXT: keep one .invariant directory at the Git repository root"],
        )

    source_path = (
        sources.resolve_content_path(repo, args.path)
        if args.path is not None
        else None
    )
    scope_input: str | None = None
    if args.repository_scope:
        scope = sources.REPOSITORY_SCOPE
    else:
        scope, scope_input = _resolve_source_scope(
            repo,
            str(args.scope),
            provider=getattr(args, "session_provider", None),
            model=getattr(args, "model", None),
            timeout=int(getattr(args, "timeout", 600)),
        )
    source = sources.create(
        url=args.url,
        path=args.path,
        scope=scope,
        scope_input=scope_input,
    )

    if sources.INDEX_PATH.as_posix() in git.changed_paths(repo):
        raise Blocked(
            "Invariant: source registration already has uncommitted changes",
            code="dirty_source_index",
            lines=[
                f"PATH: {sources.INDEX_PATH.as_posix()}",
                "NEXT: commit or discard that source-index change, then retry",
            ],
        )
    existing = next(
        (item for item in sources.load(repo) if item.identifier == source.identifier),
        None,
    )
    if existing is not None:
        if existing != source:
            raise InvariantError(
                f"Invariant: {source.reference} is already scoped to {existing.scope}",
                code="source_conflict",
            )
        return _source_result(source, "already added")

    change_id = f"source-add-{source.identifier}"
    goal = f"Add grounding source {source.origin} for {scope}."
    paths = [sources.INDEX_PATH.as_posix()]
    if source.path:
        paths.append(f".invariant/{source.path}")
    begin = [
        "task",
        "begin",
        change_id,
        "--goal",
        goal,
        "--boundary",
        "no-record",
    ]
    for path in paths:
        begin.extend(["--path", path])
    if scope != sources.REPOSITORY_SCOPE:
        for domain in _source_domains(repo, scope):
            begin.extend(["--domain", domain])
    _core(repo, *begin)
    provider = _source_provider(repo, getattr(args, "session_provider", None))
    try:
        _resolve_actions(
            repo,
            change_id,
            provider,
            model=getattr(args, "model", None),
            timeout=int(getattr(args, "timeout", 600)),
        )
        worktree = _worktree(repo, change_id)
        if source.path and source_path is not None:
            destination = worktree / ".invariant" / source.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        added = sources.add(worktree, source)
        changed = git.changed_paths(worktree)
        task = _task(repo, change_id)
        integration = task.get("integration")
        base = (
            str(integration.get("base") or "")
            if isinstance(integration, dict)
            else ""
        )
        if changed:
            candidate_commit = _commit_candidate(
                worktree, f"Add grounding source {source.identifier}"
            )
        else:
            candidate_commit = git.resolve(worktree, "HEAD") or ""
            if not added and candidate_commit == base:
                _core(repo, "task", "invalidate", change_id)
                return _source_result(source, "already added")
        finished = _finish_change(
            repo,
            change_id,
            provider,
            subject=f"Add grounding source {source.identifier}",
            model=getattr(args, "model", None),
            timeout=int(getattr(args, "timeout", 600)),
        )
    except InvariantError as exc:
        raise _identify(exc, "SOURCE", source.reference)

    task = finished["task"]
    completion = task.get("completion")
    landed = (
        str(completion.get("commit") or "")
        if isinstance(completion, dict)
        else ""
    )
    result = _source_result(source, "added", landed or candidate_commit)
    if isinstance(result.data, dict):
        result.data.update({"change": change_id, **finished})
    return result


def _identifier(prefix: str, description: str) -> str:
    words = re.findall(r"[a-z0-9]+", description.lower())[:5]
    stem = "-".join(words) or prefix
    stem = stem[:42].rstrip("-")
    return f"{prefix}-{stem}-{secrets.token_hex(4)}"


def _is_establishment(receipt: dict[str, Any]) -> bool:
    return isinstance(receipt.get("governance_run"), dict)


def _receipt_is_current(repo: Path, receipt: dict[str, Any]) -> bool:
    target = str(receipt.get("integration_target") or "")
    if target != config.resolve(repo).integration_branch:
        return False
    if receipt.get("repository") != receipts.repository_identity(repo, target):
        return False
    if receipt.get("mechanics_digest") != receipts.mechanics_digest():
        return False
    base = str(receipt.get("integration_head") or "")
    current = receipts.integration_head(repo, target)
    if "unborn" in {base, current}:
        return base == current
    return bool(base and git.is_ancestor(repo, base, current))


def _active_receipts(repo: Path) -> list[tuple[Path, dict[str, Any]]]:
    root = receipts.receipt_root(repo)
    values: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.yml")) if root.is_dir() else []:
        try:
            values.append((path, receipts.load(repo, path.stem)))
        except InvariantError:
            continue
    return values


def _resumable_establishment(repo: Path, goal: str) -> str | None:
    goal_digest = git.hash_text(repo, goal)
    candidates = [
        (path.stat().st_mtime_ns, str(receipt.get("task") or path.stem))
        for path, receipt in _active_receipts(repo)
        if _is_establishment(receipt)
        and not receipt.get("superseded_by")
        and receipt.get("goal_digest") == goal_digest
        and _receipt_is_current(repo, receipt)
    ]
    return max(candidates)[1] if candidates else None


def _supersede_equivalent_establishments(
    repo: Path, goal: str, change_id: str
) -> None:
    goal_digest = git.hash_text(repo, goal)
    for _, receipt in _active_receipts(repo):
        task = str(receipt.get("task") or "")
        if (
            task
            and task != change_id
            and _is_establishment(receipt)
            and receipt.get("goal_digest") == goal_digest
            and not receipt.get("superseded_by")
        ):
            receipt["superseded_by"] = change_id
            receipts.save(repo, task, receipt)


def _remember_establishment_failure(
    repo: Path, change_id: str, error: InvariantError
) -> None:
    try:
        receipt = receipts.load(repo, change_id)
    except InvariantError:
        return
    details: dict[str, str] = {}
    for line in error.lines:
        name, separator, value = line.partition(": ")
        if separator and name in {"CHECK", "LOG"}:
            details[name.lower()] = value
    receipt["last_failure"] = {
        "code": error.code,
        "message": error.message.removeprefix("Invariant: "),
        **details,
    }
    receipts.save(repo, change_id, receipt)


def _clear_establishment_failure(repo: Path, change_id: str) -> None:
    try:
        receipt = receipts.load(repo, change_id)
    except InvariantError:
        return
    if "last_failure" in receipt:
        receipt.pop("last_failure", None)
        receipts.save(repo, change_id, receipt)


def _present_establishment_failure(
    error: InvariantError,
    change_id: str,
    *,
    show_identifier: bool,
) -> InvariantError:
    detail = [
        line
        for line in error.lines
        if line.startswith(("CHECK: ", "LOG: ", "REQUIRES: "))
    ]
    error.lines = [
        *([f"ESTABLISH: {change_id}"] if show_identifier else []),
        "STATUS: stopped",
        "PROCESS: none — the command exited",
        *detail,
        "PRESERVED: proposed records and candidate work",
        (
            f"NEXT: invariant establish --id {change_id}"
            if show_identifier
            else "NEXT: invariant establish"
        ),
    ]
    return error


def _human_change_state(
    repo: Path, receipt: dict[str, Any]
) -> tuple[str, bool, str]:
    failure = (
        receipt.get("last_failure")
        if isinstance(receipt.get("last_failure"), dict)
        else {}
    )
    if failure:
        detail = str(failure.get("check") or failure.get("message") or "previous attempt failed")
        return "needs retry", True, detail
    lifecycle = (
        receipt.get("lifecycle")
        if isinstance(receipt.get("lifecycle"), dict)
        else {}
    )
    stage = str(lifecycle.get("stage") or "briefed")
    if stage == "awaiting-review" and config.resolve(repo).authority == "human":
        return "needs your decision", True, ""
    if stage in {"awaiting-branch", "awaiting-landing"}:
        return "needs confirmation", True, ""
    if stage == "cleanup-required":
        return "needs attention", True, ""
    return "ready to resume", False, ""


def _human_active_changes(repo: Path) -> list[dict[str, Any]]:
    regular: list[tuple[Path, dict[str, Any]]] = []
    establishments: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path, receipt in _active_receipts(repo):
        if receipt.get("superseded_by"):
            continue
        if _is_establishment(receipt):
            key = str(receipt.get("goal_digest") or receipt.get("task") or path.stem)
            establishments.setdefault(key, []).append((path, receipt))
        else:
            regular.append((path, receipt))

    selected = list(regular)
    for values in establishments.values():
        selected.append(
            max(
                values,
                key=lambda item: (
                    _receipt_is_current(repo, item[1]),
                    item[0].stat().st_mtime_ns,
                ),
            )
        )

    output: list[dict[str, Any]] = []
    for _, receipt in selected:
        establishment = _is_establishment(receipt)
        state_name, attention, detail = _human_change_state(repo, receipt)
        output.append(
            {
                "id": str(receipt.get("task") or "unknown"),
                "label": (
                    "Repository records"
                    if establishment
                    else str(receipt.get("task") or "change")
                ),
                "state": state_name,
                "attention": attention,
                "detail": detail,
                "establishment": establishment,
            }
        )
    return sorted(output, key=lambda item: (not item["establishment"], item["label"]))


def _human_decision_blocked(request: str) -> Blocked:
    return Blocked(
        "Invariant: your decision is needed before repository records can change",
        code="authority_required",
        lines=[
            "STATUS: needs-your-decision",
            f"REQUEST: {request}",
            "PROCESS: no background worker — the proposal is preserved",
            "NEXT: rerun invariant establish in an interactive terminal",
        ],
    )


def _human_finding_decision(repo: Path, change_id: str) -> None:
    receipt = receipts.load(repo, change_id)
    session = (
        receipt.get("governance_run")
        if isinstance(receipt.get("governance_run"), dict)
        else {}
    )
    audit_id = str(session.get("audit") or "")
    lifecycle = (
        receipt.get("lifecycle")
        if isinstance(receipt.get("lifecycle"), dict)
        else {}
    )
    worktree = Path(str(lifecycle.get("worktree") or repo))
    raw = load_yaml(worktree / ".invariant" / "audits" / f"{audit_id}.yml")
    findings = raw.get("findings", []) if isinstance(raw, dict) else []
    ready = [
        item
        for item in findings
        if isinstance(item, dict)
        and item.get("id")
        and item.get("disposition") == "adoptable"
    ]
    if not ready:
        _core(repo, "governance", "adopt", change_id, "--none")
        return
    if not sys.stdin.isatty():
        raise _human_decision_blocked(
            "choose all, none, or selected audited findings"
        )

    facts = ["The agent found these recordable architectural facts:", ""]
    for index, finding in enumerate(ready, start=1):
        summary = re.sub(r"\s+", " ", str(finding.get("summary") or "")).strip()
        facts.append(f"{index}. {summary or finding['id']}")
    print(style.decision("Your decision", facts))
    prompt = "Record all, none, or selected numbers (for example 1 3)"
    while True:
        answer = input(style.prompt("decide") + prompt + ": ").strip().lower()
        if answer == "all":
            _core(repo, "governance", "adopt", change_id, "--all-ready")
            return
        if answer == "none":
            _core(repo, "governance", "adopt", change_id, "--none")
            return
        try:
            indexes = sorted({int(value) for value in re.split(r"[ ,]+", answer) if value})
        except ValueError:
            indexes = []
        if indexes and all(1 <= index <= len(ready) for index in indexes):
            arguments = ["governance", "adopt", change_id]
            for index in indexes:
                arguments.extend(["--finding", str(ready[index - 1]["id"])])
            _core(repo, *arguments)
            return
        print("  Choose all, none, or one or more listed numbers.")


def _human_candidate_decisions(repo: Path, change_id: str) -> None:
    for _ in range(12):
        task = _task(repo, change_id)
        actions = [
            item
            for item in task.get("actions", [])
            if isinstance(item, dict) and item.get("id")
        ]
        if not actions:
            return
        if not sys.stdin.isatty():
            raise _human_decision_blocked(
                "accept or reject the exact proposed repository records"
            )
        action_id = str(actions[0]["id"])
        action = _result(_core(repo, "task", "action", change_id, action_id), "action")
        if not isinstance(action, dict) or action.get("kind") != "review_semantics":
            raise _human_decision_blocked(
                f"resolve the pending decision '{action_id}'"
            )
        context = action.get("context") if isinstance(action.get("context"), dict) else {}
        references = [
            str(item)
            for item in context.get("governance", [])
            if isinstance(item, str)
        ]
        print(
            style.decision(
                "Accept repository records",
                [
                    "The exact proposal is ready"
                    + (f" ({len(references)} durable references)." if references else ".")
                ],
            )
        )
        accepted = input(style.prompt("decide") + "Accept this proposal? [y/N]: ").strip().lower()
        if accepted not in {"y", "yes"}:
            raise _human_decision_blocked(
                "the proposal was not accepted; it remains available for review"
            )
        summary = input(style.prompt("decide") + "Reason (optional): ").strip()
        prepared = load_yaml(receipts.task_root(repo, change_id) / "prepared-assessment.yml")
        boundary = prepared.get("boundary") if isinstance(prepared, dict) else {}
        disposition = (
            str(boundary.get("disposition") or "no-record")
            if isinstance(boundary, dict)
            else "no-record"
        )
        response = {
            "version": 1,
            "review_id": str(context.get("review_id") or ""),
            "candidate_tree": str(context.get("candidate_tree") or ""),
            "verdict": "accepted",
            "summary": summary or "Accepted the exact proposed repository records.",
            "semantic_effect": disposition,
            "authority": f"user:task:{change_id}#review",
            "review_mode": "independent",
            "candidate_defects": [],
            "retained_discoveries": [
                str(item)
                for item in context.get("retained_discoveries", [])
                if isinstance(item, str)
            ],
        }
        with tempfile.TemporaryDirectory(prefix="invariant-human-decision.") as directory:
            source = Path(directory) / "review.json"
            source.write_text(json.dumps(response), encoding="utf-8")
            _core(repo, "task", "respond", change_id, action_id, "--input", str(source))
    raise Blocked(
        "Invariant: repository records still need a decision",
        code="action_limit_reached",
    )


def _task(repo: Path, change_id: str) -> dict[str, Any]:
    value = _result(_core(repo, "task", "status", change_id), "task")
    if not isinstance(value, dict):
        raise InvariantError("Invariant: protocol returned an invalid change")
    return value


def _worktree(repo: Path, change_id: str) -> Path:
    task = _task(repo, change_id)
    work = task.get("work")
    value = str(work.get("worktree") or "") if isinstance(work, dict) else ""
    path = Path(value) if value else None
    if path is None or not path.is_dir():
        stage = str(task.get("stage") or "paused")
        next_step = (
            f"invariant task continue {change_id} --apply"
            if stage == "awaiting-branch"
            else f"invariant status {change_id}"
        )
        raise Blocked(
            f"Invariant: change '{change_id}' is waiting before its worktree can be used",
            code="change_paused",
            lines=[
                f"CHANGE: {change_id}",
                f"STATUS: {stage}",
                f"NEXT: {next_step}",
            ],
        )
    return path.resolve()


def _resolve_actions(
    repo: Path,
    change_id: str,
    provider: AgentProvider,
    *,
    model: str | None,
    timeout: int,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for _ in range(12):
        task = _task(repo, change_id)
        actions = task.get("actions")
        pending = [item for item in actions or [] if isinstance(item, dict) and item.get("id")]
        if not pending:
            return resolved
        action_id = str(pending[0]["id"])
        namespace = argparse.Namespace(
            using=provider,
            model=model,
            timeout=timeout,
            apply=True,
            independent=False,
            task_id=change_id,
            action_id=action_id,
        )
        try:
            resolved.append(harness_cli._task_respond(namespace))
        except AgentInvocationError as exc:
            raise _agent_error(exc) from exc
    raise Blocked(
        f"Invariant: change '{change_id}' did not converge after 12 agent actions",
        code="action_limit_reached",
    )


@dataclass(frozen=True)
class _ChangeUnit:
    identifier: str
    label: str
    objective: str
    dependencies: tuple[str, ...]
    paths: tuple[str, ...]
    interfaces: tuple[str, ...]
    governance: tuple[str, ...]
    provides: tuple[str, ...]
    relies_on: tuple[str, ...]
    verifies: tuple[str, ...]

    def plan_row(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "objective": self.objective,
            "dependencies": list(self.dependencies),
            "paths": list(self.paths),
            "interfaces": list(self.interfaces),
            "governance": list(self.governance),
            "provides": list(self.provides),
            "relies_on": list(self.relies_on),
            "verifies": list(self.verifies),
        }


@dataclass(frozen=True)
class _ChangePlan:
    strategy: str
    summary: str
    units: tuple[_ChangeUnit, ...] = ()

    @property
    def parallel(self) -> bool:
        return self.strategy == "parallel"


def _change_plan_schema() -> dict[str, Any]:
    string_list = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["strategy", "summary", "units"],
        "properties": {
            "strategy": {"type": "string", "enum": ["single", "parallel"]},
            "summary": {"type": "string", "minLength": 1},
            "units": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "objective",
                        "dependencies",
                        "paths",
                        "interfaces",
                        "governance",
                        "provides",
                        "relies_on",
                        "verifies",
                    ],
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$",
                        },
                        "objective": {"type": "string", "minLength": 1},
                        "dependencies": string_list,
                        "paths": string_list,
                        "interfaces": string_list,
                        "governance": string_list,
                        "provides": string_list,
                        "relies_on": string_list,
                        "verifies": string_list,
                    },
                },
            },
        },
    }


def _change_plan_prompt(repo: Path, goal: str) -> str:
    return (
        "Classify one requested repository change before implementation. Inspect the repository "
        "read-only and return exactly one JSON object matching the supplied schema. Choose single "
        "for a small, cohesive, tightly coupled, or uncertain change. Choose parallel only when at "
        "least two work items can make meaningful progress independently with non-overlapping path, "
        "interface, and governance claims. Do not manufacture work merely to use more workers.\n\n"
        "For a parallel plan, give every work item a short stable id, a self-contained objective, "
        "repository-relative path prefixes without globs, exact interface and governance claims, "
        "and at least one executable verifier locator (command:<executable-path>, test:<test-path>, "
        "schema:<executable-path>, or a configured runner:<name>#<target>). Unordered work items must "
        "have disjoint claims.\n\n"
        "Contract synchronization is causal. Work items that consume an unchanged accepted contract "
        "may run concurrently. If a work item creates or evolves a contract, make it the sole provider "
        "by listing the same contract locator in governance and provides. Every affected consumer must "
        "list that locator in relies_on and depend on the provider. The host will converge providers "
        "before creating dependent worktrees. A frontend and backend may therefore run concurrently "
        "against a stable contract, while consumers of an evolving contract must follow its provider.\n\n"
        "For strategy=single, return an empty units array. For strategy=parallel, return between two "
        "and eight units.\n\n"
        f"Request:\n{goal.strip()}\n"
        f"{_grounding_prompt(repo)}"
    )


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise AgentInvocationError(
            f"change planner returned invalid {label}", code="invalid_agent_output"
        )
    return tuple(sorted(set(item.strip() for item in value)))


def _parse_change_plan(
    change_id: str, response: dict[str, Any]
) -> _ChangePlan:
    strategy = response.get("strategy")
    summary = response.get("summary")
    raw_units = response.get("units")
    if strategy not in {"single", "parallel"} or not isinstance(summary, str) or not summary.strip():
        raise AgentInvocationError(
            "change planner returned an invalid strategy", code="invalid_agent_output"
        )
    if not isinstance(raw_units, list):
        raise AgentInvocationError(
            "change planner returned invalid work items", code="invalid_agent_output"
        )
    if strategy == "single":
        if raw_units:
            raise AgentInvocationError(
                "single change plan must not contain work items", code="invalid_agent_output"
            )
        return _ChangePlan("single", summary.strip())
    if not 2 <= len(raw_units) <= 8:
        raise AgentInvocationError(
            "parallel change plan must contain two to eight work items",
            code="invalid_agent_output",
        )

    labels: list[str] = []
    rows: list[dict[str, Any]] = []
    for raw in raw_units:
        if not isinstance(raw, dict):
            raise AgentInvocationError(
                "change planner returned an invalid work item", code="invalid_agent_output"
            )
        label = raw.get("id")
        if not isinstance(label, str) or not git.valid_id(label):
            raise AgentInvocationError(
                "change planner returned an invalid work item id", code="invalid_agent_output"
            )
        if label in labels:
            raise AgentInvocationError(
                f"change planner returned duplicate work item '{label}'",
                code="invalid_agent_output",
            )
        labels.append(label)
        rows.append(raw)

    identifiers = {label: f"{change_id}.{label}" for label in labels}
    units: list[_ChangeUnit] = []
    for raw, label in zip(rows, labels, strict=True):
        objective = raw.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise AgentInvocationError(
                f"change planner returned no objective for '{label}'",
                code="invalid_agent_output",
            )
        raw_dependencies = _string_tuple(raw.get("dependencies"), f"dependencies for '{label}'")
        missing = [item for item in raw_dependencies if item not in identifiers]
        if missing:
            raise AgentInvocationError(
                f"change planner made '{label}' depend on missing work item '{missing[0]}'",
                code="invalid_agent_output",
            )
        units.append(
            _ChangeUnit(
                identifier=identifiers[label],
                label=label,
                objective=objective.strip(),
                dependencies=tuple(identifiers[item] for item in raw_dependencies),
                paths=_string_tuple(raw.get("paths"), f"paths for '{label}'"),
                interfaces=_string_tuple(raw.get("interfaces"), f"interfaces for '{label}'"),
                governance=_string_tuple(raw.get("governance"), f"governance for '{label}'"),
                provides=_string_tuple(raw.get("provides"), f"provides for '{label}'"),
                relies_on=_string_tuple(raw.get("relies_on"), f"relies_on for '{label}'"),
                verifies=_string_tuple(raw.get("verifies"), f"verifiers for '{label}'"),
            )
        )
    return _ChangePlan("parallel", summary.strip(), tuple(units))


def _plan_change(
    provider: AgentProvider,
    repo: Path,
    change_id: str,
    goal: str,
    *,
    model: str | None,
    timeout: int,
) -> tuple[_ChangePlan, dict[str, Any]]:
    try:
        result = invoke(
            provider,
            repo,
            _change_plan_prompt(repo, goal),
            _change_plan_schema(),
            model=model,
            timeout=timeout,
        )
    except AgentInvocationError:
        raise
    return _parse_change_plan(change_id, result.response), result.usage


def _change_plan_path(repo: Path, change_id: str) -> Path:
    return receipts.task_root(repo, change_id) / "coordination-plan.yml"


def _runtime_plan_path(repo: Path, change_id: str) -> Path:
    return coordinate.runtime_root(repo) / "plans" / f"{change_id}.yml"


def _persist_change_plan(
    repo: Path,
    change_id: str,
    goal: str,
    plan: _ChangePlan,
    *,
    target: str,
    ground: str,
    domains: list[str],
) -> None:
    receipt = receipts.load(repo, change_id)
    coordination_state = {
        "strategy": plan.strategy,
        "summary": plan.summary,
        "plan": change_id if plan.parallel else "",
        "units": [unit.identifier for unit in plan.units],
    }
    if not plan.parallel:
        receipt["coordination"] = coordination_state
        receipts.save(repo, change_id, receipt)
        return
    document = {
        "version": 1,
        "id": change_id,
        "goal": goal.strip(),
        "summary": plan.summary,
        "integration_target": target,
        "integration_ground": ground,
        "domains": sorted(set(domains)),
        "governing_digest": governance.digest(repo, domains),
        "units": [unit.plan_row() for unit in plan.units],
    }
    local = _change_plan_path(repo, change_id)
    runtime = _runtime_plan_path(repo, change_id)
    local.parent.mkdir(parents=True, exist_ok=True)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml(local, document)
    dump_yaml(runtime, document)
    try:
        coordinate.validate_plan(repo, change_id)
    except InvariantError:
        local.unlink(missing_ok=True)
        runtime.unlink(missing_ok=True)
        raise
    receipt["coordination"] = coordination_state
    receipts.save(repo, change_id, receipt)


def _load_change_plan(repo: Path, change_id: str) -> _ChangePlan | None:
    path = _change_plan_path(repo, change_id)
    if not path.is_file():
        return None
    raw = load_yaml(path)
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise InvariantError(
            f"Invariant: saved parallel plan for '{change_id}' is invalid",
            code="invalid_plan",
        )
    runtime = _runtime_plan_path(repo, change_id)
    if not runtime.is_file():
        runtime.parent.mkdir(parents=True, exist_ok=True)
        dump_yaml(runtime, raw)
    coordinate.validate_plan(repo, change_id)
    units: list[_ChangeUnit] = []
    for row in raw.get("units", []):
        if not isinstance(row, dict):
            raise InvariantError(
                f"Invariant: saved parallel plan for '{change_id}' is invalid",
                code="invalid_plan",
            )
        identifier = str(row.get("id") or "")
        label = identifier.removeprefix(f"{change_id}.")
        units.append(
            _ChangeUnit(
                identifier=identifier,
                label=label,
                objective=str(row.get("objective") or ""),
                dependencies=_string_tuple(row.get("dependencies", []), f"dependencies for '{label}'"),
                paths=_string_tuple(row.get("paths", []), f"paths for '{label}'"),
                interfaces=_string_tuple(row.get("interfaces", []), f"interfaces for '{label}'"),
                governance=_string_tuple(row.get("governance", []), f"governance for '{label}'"),
                provides=_string_tuple(row.get("provides", []), f"provides for '{label}'"),
                relies_on=_string_tuple(row.get("relies_on", []), f"relies_on for '{label}'"),
                verifies=_string_tuple(row.get("verifies", []), f"verifiers for '{label}'"),
            )
        )
    return _ChangePlan(
        "parallel",
        str(raw.get("summary") or "Resumed saved parallel plan."),
        tuple(units),
    )


def _coordination_state_path(repo: Path, change_id: str) -> Path:
    return receipts.task_root(repo, change_id) / "coordination-state.yml"


def _load_coordination_state(repo: Path, change_id: str) -> dict[str, dict[str, str]]:
    path = _coordination_state_path(repo, change_id)
    if not path.is_file():
        return {}
    raw = load_yaml(path)
    rows = raw.get("units", []) if isinstance(raw, dict) else []
    return {
        str(row.get("id")): {str(key): str(value) for key, value in row.items()}
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def _save_coordination_state(
    repo: Path, change_id: str, state: dict[str, dict[str, str]]
) -> None:
    dump_yaml(
        _coordination_state_path(repo, change_id),
        {"version": 1, "plan": change_id, "units": list(state.values())},
    )


def _unit_branch(change_id: str, label: str) -> str:
    return f"invariant/work/{change_id}-{label}-{secrets.token_hex(6)}"


def _ensure_unit_worktree(
    repo: Path,
    change_id: str,
    unit: _ChangeUnit,
    base: str,
    target: str,
    state: dict[str, dict[str, str]],
) -> tuple[str, Path]:
    saved = state.get(unit.identifier, {})
    branch = saved.get("branch", "")
    worktree_value = saved.get("worktree", "")
    worktree = Path(worktree_value) if worktree_value else None
    if not branch or not git.branch_exists(repo, branch) or worktree is None or not worktree.is_dir():
        branch = _unit_branch(change_id, unit.label)
        worktree = coordinate.ensure_runtime(repo) / "worktrees" / branch.removeprefix("invariant/work/")
        if git.branch_exists(repo, branch) or worktree.exists():
            raise InvariantError(
                f"Invariant: generated work item '{unit.label}' already exists",
                code="task_worktree_exists",
            )
        git.run(
            ["worktree", "add", "--quiet", "-b", branch, str(worktree), base],
            cwd=repo,
        )
        worktree = worktree.resolve()
        state[unit.identifier] = {
            "id": unit.identifier,
            "label": unit.label,
            "status": "active",
            "base": base,
            "branch": branch,
            "worktree": str(worktree),
        }
        _save_coordination_state(repo, change_id, state)
    lease = coordinate.runtime_root(repo) / "leases" / f"{unit.identifier}.yml"
    if lease.is_file():
        coordinate.renew_lease(repo, unit.identifier)
    else:
        coordinate.create_lease(
            repo,
            unit.identifier,
            paths=unit.paths,
            interfaces=unit.interfaces,
            governance_claims=unit.governance,
            branch=branch,
            worktree=str(worktree),
            task=change_id,
            owner=f"change:{change_id}",
            integration_target=target,
        )
    return branch, worktree


def _change_unit_prompt(
    repo: Path, change_id: str, goal: str, unit: _ChangeUnit
) -> str:
    dependencies = ", ".join(unit.dependencies) or "none"
    return (
        "You are implementing one work item in an Invariant-managed parallel change. Read the "
        "repository instructions and inspect the converged checkout before editing. Work only in "
        "the current checkout and only within the owned path prefixes below. Implement the objective "
        "completely and run its declared verification. Do not invoke Invariant, create commits, push, "
        "publish, or edit unrelated paths. Dependency providers have already converged into this "
        "checkout; consume their current contract rather than reconstructing an older assumption. "
        "Leave completed edits in the working tree and end with a concise summary.\n\n"
        f"Change ID: {change_id}\nOverall request:\n{goal.strip()}\n\n"
        f"Work item: {unit.label}\nObjective: {unit.objective}\n"
        f"Dependencies: {dependencies}\nOwned paths: {', '.join(unit.paths)}\n"
        f"Interfaces: {', '.join(unit.interfaces) or 'none'}\n"
        f"Governance: {', '.join(unit.governance) or 'none'}\n"
        f"Provides: {', '.join(unit.provides) or 'none'}\n"
        f"Relies on: {', '.join(unit.relies_on) or 'none'}\n"
        f"Verify: {', '.join(unit.verifies)}\n"
        f"{_grounding_prompt(repo)}"
    )


def _validate_unit_paths(unit: _ChangeUnit, changed: list[str]) -> None:
    for path in changed:
        if not any(governance.paths_related(path, claim) for claim in unit.paths):
            raise Blocked(
                f"Invariant: parallel work item '{unit.label}' changed unclaimed path '{path}'",
                code="parallel_claim_violation",
                lines=[
                    f"WORK-ITEM: {unit.label}",
                    f"CLAIMS: {', '.join(unit.paths)}",
                    "RECOVERY: work item branch and worktree retained; aggregate candidate unchanged",
                ],
            )


def _prepare_parallel_unit(
    provider: AgentProvider,
    worktree: Path,
    change_id: str,
    goal: str,
    unit: _ChangeUnit,
    *,
    model: str | None,
    timeout: int,
) -> AgentWriteResult:
    return invoke_change(
        provider,
        worktree,
        _change_unit_prompt(worktree, change_id, goal, unit),
        model=model,
        timeout=timeout,
    )


def _merge_parallel_unit(
    repo: Path,
    convergence: Path,
    change_id: str,
    unit: _ChangeUnit,
    branch: str,
    worktree: Path,
) -> None:
    merged = git.run(
        [
            "merge",
            "--no-ff",
            "-m",
            f"Invariant work item: {unit.label}",
            "-m",
            f"Invariant-Plan: {change_id}\nInvariant-Work-Item: {unit.identifier}",
            branch,
        ],
        cwd=convergence,
        check=False,
    )
    if merged.returncode:
        git.run(["merge", "--abort"], cwd=convergence, check=False)
        raise Blocked(
            f"Invariant: parallel work item '{unit.label}' did not converge cleanly",
            code="merge_conflict",
            lines=[
                f"GIT: {merged.stderr or merged.stdout or 'merge conflict'}",
                "RECOVERY: work item branch retained; integration target unchanged",
            ],
        )


def _cleanup_parallel_unit(
    repo: Path,
    convergence: Path,
    unit: _ChangeUnit,
    branch: str,
    worktree: Path,
) -> None:
    coordinate.release_lease(repo, unit.identifier, missing_ok=True)
    if worktree.is_dir():
        git.run(["worktree", "remove", str(worktree)], cwd=repo, check=False)
    convergence_head = git.resolve(convergence, "HEAD") or ""
    if (
        convergence_head
        and git.branch_exists(repo, branch)
        and git.is_ancestor(repo, f"refs/heads/{branch}", convergence_head)
    ):
        git.run(["branch", "-D", branch], cwd=repo, check=False)


def _aggregate_usage(values: list[dict[str, Any]]) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for value in values:
        for name, item in value.items():
            prior = usage.get(name)
            usage[name] = (
                prior + item
                if isinstance(prior, (int, float)) and isinstance(item, (int, float))
                else item
            )
    return usage


def _run_parallel_change(
    repo: Path,
    convergence: Path,
    change_id: str,
    goal: str,
    plan: _ChangePlan,
    provider: AgentProvider,
    *,
    target: str,
    model: str | None,
    timeout: int,
) -> AgentWriteResult:
    state = _load_coordination_state(repo, change_id)
    completed = {
        identifier
        for identifier, row in state.items()
        if row.get("status") == "merged"
    }
    messages: list[str] = []
    sessions: list[str] = []
    usages: list[dict[str, Any]] = []
    units = {unit.identifier: unit for unit in plan.units}
    for identifier in completed:
        row = state[identifier]
        unit = units.get(identifier)
        if unit is not None and row.get("branch") and row.get("worktree"):
            _cleanup_parallel_unit(
                repo,
                convergence,
                unit,
                row["branch"],
                Path(row["worktree"]),
            )
    while len(completed) < len(units):
        ready = [
            unit
            for unit in plan.units
            if unit.identifier not in completed
            and set(unit.dependencies).issubset(completed)
        ]
        if not ready:
            raise InvariantError(
                f"Invariant: parallel plan '{change_id}' has no dispatchable work item",
                code="invalid_plan",
            )
        base = git.resolve(convergence, "HEAD") or ""
        prepared: dict[str, tuple[_ChangeUnit, str, Path, AgentWriteResult | None]] = {}
        to_invoke: list[tuple[_ChangeUnit, str, Path]] = []
        for unit in ready:
            branch, worktree = _ensure_unit_worktree(
                repo, change_id, unit, base, target, state
            )
            row = state[unit.identifier]
            branch_head = git.resolve(worktree, "HEAD") or ""
            if row.get("status") == "prepared" and branch_head != row.get("base"):
                prepared[unit.identifier] = (unit, branch, worktree, None)
            else:
                to_invoke.append((unit, branch, worktree))

        failures: list[Exception] = []
        if to_invoke:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(4, len(to_invoke))
            ) as executor:
                futures = {
                    executor.submit(
                        _prepare_parallel_unit,
                        provider,
                        worktree,
                        change_id,
                        goal,
                        unit,
                        model=model,
                        timeout=timeout,
                    ): (unit, branch, worktree)
                    for unit, branch, worktree in to_invoke
                }
                for future in concurrent.futures.as_completed(futures):
                    unit, branch, worktree = futures[future]
                    try:
                        result = future.result()
                        changed = git.changed_paths(worktree)
                        _validate_unit_paths(unit, changed)
                        commit = _commit_candidate(worktree, unit.objective)
                        state[unit.identifier].update(
                            {"status": "prepared", "commit": commit, "summary": result.message}
                        )
                        _save_coordination_state(repo, change_id, state)
                        prepared[unit.identifier] = (unit, branch, worktree, result)
                    except Exception as exc:
                        failures.append(exc)
        if failures:
            raise failures[0]

        for unit in ready:
            prepared_unit, branch, worktree, result = prepared[unit.identifier]
            _merge_parallel_unit(
                repo, convergence, change_id, prepared_unit, branch, worktree
            )
            state[unit.identifier]["status"] = "merged"
            _save_coordination_state(repo, change_id, state)
            _cleanup_parallel_unit(
                repo, convergence, prepared_unit, branch, worktree
            )
            completed.add(unit.identifier)
            if result is not None:
                messages.append(f"{unit.label}: {result.message}")
                if result.session_id:
                    sessions.append(result.session_id)
                usages.append(result.usage)
    return AgentWriteResult(
        provider,
        " ".join(messages),
        ",".join(sessions),
        _aggregate_usage(usages),
    )


def _acquire_convergence_lease(
    repo: Path,
    change_id: str,
    convergence: Path,
    plan: _ChangePlan,
    *,
    target: str,
    base: str,
    domains: list[str],
    selected_interfaces: list[str],
) -> None:
    paths = sorted({path for unit in plan.units for path in unit.paths})
    interfaces = sorted(
        {name for unit in plan.units for name in unit.interfaces}.union(
            selected_interfaces
        )
    )
    governance_claims = {claim for unit in plan.units for claim in unit.governance}
    context = governance.context_result(
        convergence,
        paths=git.changed_paths(convergence, base),
        base=base,
        domains_selected=domains,
        interfaces=interfaces,
    )
    governance_claims.update(
        f"{item.kind}:{item.identifier}" for item in context.affected
    )
    lease = coordinate.runtime_root(repo) / "leases" / f"{change_id}.yml"
    if lease.is_file():
        coordinate.release_lease(repo, change_id)
    coordinate.create_lease(
        repo,
        change_id,
        paths=paths,
        interfaces=interfaces,
        governance_claims=sorted(governance_claims),
        domains=domains,
        digest=governance.digest(repo, domains) if domains else None,
        branch=git.current_branch(convergence),
        worktree=str(convergence),
        task=change_id,
        owner=f"change:{change_id}:convergence",
        integration_target=target,
    )


def _change_prompt(repo: Path, change_id: str, goal: str) -> str:
    return (
        "You are implementing one repository change inside an Invariant-managed isolated "
        "worktree. Read the repository instructions and inspect the existing code before editing. "
        "Implement the request completely and run focused checks when useful. Work only inside "
        "the current checkout. Do not invoke Invariant, edit its runtime receipts, create commits, "
        "push, publish, or perform unrelated external actions; Invariant owns verification and "
        "landing. Leave the completed edits in the working tree and end with a concise summary.\n\n"
        f"Change ID: {change_id}\nRequest:\n{goal.strip()}\n"
        f"{_grounding_prompt(repo)}"
    )


def _commit_candidate(worktree: Path, subject: str) -> str:
    paths = git.changed_paths(worktree)
    if not paths:
        raise Blocked(
            "Invariant: the coding agent completed without changing the candidate",
            code="empty_change",
        )
    git.run(["add", "-A"], cwd=worktree)
    concise = re.sub(r"\s+", " ", subject).strip()[:64].rstrip(" .")
    git.run(["commit", "-q", "-m", f"Invariant change: {concise}"], cwd=worktree)
    return git.resolve(worktree, "HEAD") or ""


def _finish_change(
    repo: Path,
    change_id: str,
    provider: AgentProvider,
    *,
    subject: str,
    model: str | None,
    timeout: int,
    checks: tuple[str, ...] = (),
) -> dict[str, Any]:
    arguments = ["task", "finish", change_id, "--subject", subject]
    for check in checks:
        arguments.extend(["--check", check])
    payload = _core(repo, *arguments)
    _resolve_actions(repo, change_id, provider, model=model, timeout=timeout)
    task = _task(repo, change_id)
    if task.get("stage") != "completed":
        raise Blocked(
            f"Invariant: change '{change_id}' still needs input",
            code="change_needs_input",
            lines=[f"CHANGE: {change_id}", f"STATUS: {task.get('stage') or 'unknown'}"],
        )
    return {"finish": payload.get("result", {}), "task": task}


def _change(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    if not args.prompt.strip():
        raise UsageError("Invariant: change description cannot be empty")
    provider = _resolve_provider(repo, args.using)
    change_id = args.change_id or _identifier("change", args.prompt)
    preview = {
        "id": change_id,
        "provider": provider.value,
        "operation": "change",
        "mode": "isolated-worktree",
        "invoked": False,
    }
    if args.dry_run:
        return CommandResult(
            [
                f"CHANGE: {change_id}",
                f"AGENT: {provider.value}",
                "MODE: isolated-worktree",
                "STATUS: preview",
            ],
            preview,
        )
    begin = [
        "task",
        "begin",
        change_id,
        "--goal",
        args.prompt,
        "--boundary",
        args.boundary,
    ]
    for option, values in (
        ("--path", args.path),
        ("--interface", args.interface),
        ("--domain", args.domain),
    ):
        for value in values:
            begin.extend([option, value])
    _core(repo, *begin)
    plan: _ChangePlan | None = None
    plan_usage: dict[str, Any] = {}
    try:
        with style.activity("Preparing managed change", done="Prepared managed change"):
            _resolve_actions(
                repo, change_id, provider, model=args.model, timeout=args.timeout
            )
            worktree = _worktree(repo, change_id)
            task = _task(repo, change_id)
            integration = task.get("integration")
            target = (
                str(integration.get("target") or "")
                if isinstance(integration, dict)
                else ""
            )
            base = (
                str(integration.get("base") or "")
                if isinstance(integration, dict)
                else ""
            )
        plan = _load_change_plan(repo, change_id)
        if plan is None:
            with style.activity(
                "Choosing the smallest safe execution plan",
                done="Chose the execution plan",
            ):
                plan, plan_usage = _plan_change(
                    provider,
                    worktree,
                    change_id,
                    args.prompt,
                    model=args.model,
                    timeout=args.timeout,
                )
                _persist_change_plan(
                    repo,
                    change_id,
                    args.prompt,
                    plan,
                    target=target,
                    ground=base,
                    domains=args.domain,
                )
        if plan.parallel:
            with style.activity(
                f"{_provider_name(provider)} is implementing {len(plan.units)} coordinated work items",
                done=f"{_provider_name(provider)} implemented the coordinated work items",
            ):
                agent = _run_parallel_change(
                    repo,
                    worktree,
                    change_id,
                    args.prompt,
                    plan,
                    provider,
                    target=target,
                    model=args.model,
                    timeout=args.timeout,
                )
            candidate_commit = git.resolve(worktree, "HEAD") or ""
            if not candidate_commit or candidate_commit == base:
                raise Blocked(
                    "Invariant: parallel workers completed without changing the candidate",
                    code="empty_change",
                )
            _acquire_convergence_lease(
                repo,
                change_id,
                worktree,
                plan,
                target=target,
                base=base,
                domains=args.domain,
                selected_interfaces=args.interface,
            )
            checks = tuple(
                sorted({check for unit in plan.units for check in unit.verifies})
            )
        else:
            with style.activity(
                f"{_provider_name(provider)} is implementing the change",
                done=f"{_provider_name(provider)} implemented the change",
            ):
                agent = invoke_change(
                    provider,
                    worktree,
                    _change_prompt(worktree, change_id, args.prompt),
                    model=args.model,
                    timeout=args.timeout,
                )
            candidate_commit = _commit_candidate(worktree, args.prompt)
            checks = ()
        subject_text = re.sub(r"\s+", " ", args.prompt).strip()[:64]
        with style.activity(
            "Verifying and landing the exact change", done="Verified and landed the exact change"
        ):
            finished = _finish_change(
                repo,
                change_id,
                provider,
                subject=f"Invariant change: {subject_text}",
                model=args.model,
                timeout=args.timeout,
                checks=checks,
            )
    except AgentInvocationError as exc:
        raise _identify(_agent_error(exc), "CHANGE", change_id) from exc
    except InvariantError as exc:
        raise _identify(exc, "CHANGE", change_id)
    task = finished["task"]
    completion = task.get("completion")
    landed = str(completion.get("commit") or "") if isinstance(completion, dict) else ""
    lines = [
        f"CHANGE: {change_id}",
        f"AGENT: {provider.value}",
        (
            f"PLAN: parallel — {len(plan.units)} work items"
            if plan and plan.parallel
            else "PLAN: single"
        ),
        "STATUS: complete",
        f"COMMIT: {landed or candidate_commit}",
    ]
    if agent.message:
        summary_text = re.sub(r"\s+", " ", agent.message).strip()
        lines.append(f"SUMMARY: {summary_text}")
    return CommandResult(
        lines,
        {
            **preview,
            "invoked": True,
            "status": "completed",
            "candidate_commit": candidate_commit,
            "commit": landed,
            "session_id": agent.session_id,
            "usage": _aggregate_usage([plan_usage, agent.usage]),
            "summary": agent.message,
            "plan": {
                "strategy": plan.strategy if plan else "single",
                "summary": plan.summary if plan else "",
                "units": [unit.plan_row() for unit in plan.units] if plan else [],
            },
            **finished,
        },
    )


def _establish(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    provider = _resolve_provider(repo, args.using)
    goal = args.goal or (
        "Establish or reconcile the repository's durable responsibilities, decisions, "
        "contracts, and constraints from grounded evidence."
    )
    resumed_id = None if args.change_id else _resumable_establishment(repo, goal)
    change_id = args.change_id or resumed_id or _identifier("establish", goal)
    preview = {
        "id": change_id,
        "provider": provider.value,
        "operation": "establish",
        "mode": "read-only-audit-then-managed-write",
        "invoked": False,
        "resumed": resumed_id is not None,
    }
    if args.dry_run:
        return CommandResult(
            [
                f"ESTABLISH: {change_id}",
                f"AGENT: {provider.value}",
                "MODE: inspect-then-establish",
                f"STATUS: {'resume' if resumed_id else 'preview'}",
            ],
            preview,
        )
    namespace = argparse.Namespace(
        using=provider,
        model=args.model,
        timeout=args.timeout,
        apply=True,
        task_id=change_id,
    )
    audit_result: dict[str, Any] = {}
    final: dict[str, Any] = {}
    try:
        existing: dict[str, Any] | None = None
        try:
            existing = _core(repo, "governance", "status", change_id)
        except Blocked as exc:
            if exc.code != "missing_task":
                raise
        if existing is None:
            _core(repo, "governance", "begin", change_id, "--goal", goal)
        if not args.change_id:
            _supersede_equivalent_establishments(repo, goal, change_id)
        _clear_establishment_failure(repo, change_id)

        task = _task(repo, change_id)
        if task.get("stage") != "completed":
            governance_status = _core(repo, "governance", "status", change_id)
            status_records = _result(governance_status, "records")
            values = {
                str(item.get("name")): str(item.get("value") or "")
                for item in status_records or []
                if isinstance(item, dict) and item.get("name")
            }
            phase = values.get("GOVERNANCE-PHASE", "audit")

            if phase == "audit":
                with style.activity(
                    f"{_provider_name(provider)} is inspecting the repository",
                    done=f"{_provider_name(provider)} inspected the repository",
                ):
                    audit_result = harness_cli._governance_audit(namespace)
                governance_status = _core(repo, "governance", "status", change_id)
                status_records = _result(governance_status, "records")
                values = {
                    str(item.get("name")): str(item.get("value") or "")
                    for item in status_records or []
                    if isinstance(item, dict) and item.get("name")
                }
                phase = values.get("GOVERNANCE-PHASE", "audit")

            if config.resolve(repo).authority == "human" and phase == "decision":
                _human_finding_decision(repo, change_id)
                governance_status = _core(repo, "governance", "status", change_id)
                status_records = _result(governance_status, "records")
                values = {
                    str(item.get("name")): str(item.get("value") or "")
                    for item in status_records or []
                    if isinstance(item, dict) and item.get("name")
                }
                phase = values.get("GOVERNANCE-PHASE", "decision")

            if phase in {"decision", "adopt"}:
                selected = values.get("SELECTED-FINDINGS", "")
                if selected in {"", "none", "none ready"}:
                    final = _core(repo, "governance", "defer", change_id)
                    phase = "deferred"
                else:
                    with style.activity(
                        "Preparing durable repository records",
                        done="Prepared durable repository records",
                    ):
                        _core(repo, "governance", "project", change_id)
                    phase = "authoring"

            task = _task(repo, change_id)
            if phase in {"authoring", "deferred"} and task.get("stage") in {
                "implementing",
                "implementing-unborn",
            }:
                worktree = _worktree(repo, change_id)
                if git.changed_paths(worktree):
                    _commit_candidate(worktree, "Establish repository records")
                with style.activity(
                    "Verifying and landing repository records",
                    done="Verified and landed repository records",
                ):
                    final = _core(
                        repo,
                        "task",
                        "finish",
                        change_id,
                        "--subject",
                        "Establish repository records",
                    )
            if config.resolve(repo).authority == "human":
                _human_candidate_decisions(repo, change_id)
            else:
                with style.activity(
                    f"{_provider_name(provider)} is reviewing the result",
                    done=f"{_provider_name(provider)} reviewed the result",
                ):
                    _resolve_actions(
                        repo, change_id, provider, model=args.model, timeout=args.timeout
                    )
        task = _task(repo, change_id)
    except AgentInvocationError as exc:
        error = _agent_error(exc)
        _remember_establishment_failure(repo, change_id, error)
        raise _present_establishment_failure(
            error,
            change_id,
            show_identifier=bool(args.change_id or args.verbose),
        ) from exc
    except InvariantError as exc:
        if exc.code == "authority_required":
            raise
        if exc.code == "initialization_not_committed":
            exc.lines.append(
                "REQUIRES: commit the initialization on the integration branch"
            )
        _remember_establishment_failure(repo, change_id, exc)
        raise _present_establishment_failure(
            exc,
            change_id,
            show_identifier=bool(args.change_id or args.verbose),
        )
    if task.get("stage") != "completed":
        raise Blocked(
            f"Invariant: establishment '{change_id}' still needs input",
            code="establish_needs_input",
            lines=[f"ESTABLISH: {change_id}", f"STATUS: {task.get('stage') or 'unknown'}"],
        )
    completion = task.get("completion")
    commit = str(completion.get("commit") or "") if isinstance(completion, dict) else ""
    return CommandResult(
        [
            f"ESTABLISH: {change_id}",
            f"AGENT: {provider.value}",
            "STATUS: complete",
            f"COMMIT: {commit}",
        ],
        {
            **preview,
            "invoked": True,
            "status": "completed",
            "commit": commit,
            "audit": audit_result,
            "final": final.get("result", {}),
            "task": task,
        },
    )


def _status(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    arguments = ["status", args.change_id] if args.change_id else ["status"]
    payload = _core(repo, *arguments)
    result = payload.get("result", {})
    records = result.get("records") if isinstance(result, dict) else []
    lines: list[str]
    if args.change_id:
        task = result.get("task") if isinstance(result, dict) else None
        raw_values = {
            str(item.get("name")): str(item.get("value") or "")
            for item in records or []
            if isinstance(item, dict) and item.get("name")
        }
        stage_names = {
            "briefed": "planning",
            "briefing": "planning",
            "awaiting-branch": "waiting",
            "implementing": "ready to resume",
            "implementing-unborn": "ready to resume",
            "awaiting-review": "reviewing",
            "awaiting-landing": "checking",
            "cleanup-required": "blocked",
            "completed": "complete",
        }
        impact_names = {
            "no-record": "routine",
            "recorded": "records updated",
            "unresolved": "unclear",
        }
        try:
            active_receipt = receipts.load(repo, args.change_id)
        except InvariantError:
            active_receipt = None
        if active_receipt is not None:
            lifecycle = (
                active_receipt.get("lifecycle")
                if isinstance(active_receipt.get("lifecycle"), dict)
                else {}
            )
            worktree = str(lifecycle.get("worktree") or "none")
            classification = (
                active_receipt.get("change_classification")
                if isinstance(active_receipt.get("change_classification"), dict)
                else {}
            )
            stage, _, failure_detail = _human_change_state(repo, active_receipt)
            establishment = _is_establishment(active_receipt)
            lines = [
                f"CHANGE: {args.change_id}",
                f"STATUS: {stage}",
                f"IMPACT: {impact_names.get(str(classification.get('boundary') or ''), 'covered')}",
                "COMMIT: not landed",
                "ACTIVITY: persisted state — no background worker",
            ]
            if failure_detail:
                lines.append(f"FAILED: {failure_detail}")
            if establishment:
                lines.append("NEXT: invariant establish")
            if args.verbose:
                lines.append(f"WORKTREE: {worktree}")
        elif isinstance(task, dict):
            work = task.get("work") if isinstance(task.get("work"), dict) else {}
            completion = (
                task.get("completion") if isinstance(task.get("completion"), dict) else {}
            )
            raw_stage = str(task.get("stage") or "")
            stage = stage_names.get(raw_stage, raw_stage or "unknown")
            impact = impact_names.get(str(task.get("boundary") or ""), "covered")
            lines = [
                f"CHANGE: {task.get('id') or args.change_id}",
                f"STATUS: {stage}",
                f"IMPACT: {impact}",
                f"COMMIT: {completion.get('commit') or 'not landed'}",
            ]
            if raw_stage != "completed":
                lines.append("ACTIVITY: persisted state — no background worker")
            if args.verbose:
                lines.append(f"WORKTREE: {work.get('worktree') or 'none'}")
        else:
            raw_stage = raw_values.get("STATUS", "unknown")
            boundary = raw_values.get("BOUNDARY", "unresolved")
            lines = [
                f"CHANGE: {args.change_id}",
                f"STATUS: {stage_names.get(raw_stage, raw_stage)}",
                f"IMPACT: {impact_names.get(boundary, 'covered')}",
                f"COMMIT: {raw_values.get('LANDING-COMMIT') or 'not landed'}",
            ]
            if args.verbose and raw_values.get("WORKTREE"):
                lines.append(f"WORKTREE: {raw_values['WORKTREE']}")
        connections = []
    else:
        resolved = config.resolve(repo)
        harness = preferences.repo_harness(repo)
        providers = preferences.harness_candidates(repo)
        effective = providers[0]
        connections = [_connection_payload(provider) for provider in providers]
        try:
            source_count: int | str = len(sources.load(repo))
        except InvariantError:
            source_count = "invalid"
        raw_values = {
            str(item.get("name")): str(item.get("value") or "")
            for item in records or []
            if isinstance(item, dict) and item.get("name")
        }
        valid = raw_values.get("STATE") == "valid"
        changes = _human_active_changes(repo)
        active_count = len(changes)
        attention = any(bool(item["attention"]) for item in changes)
        status = (
            "needs attention"
            if not valid
            else f"{active_count} changes need attention"
            if active_count != 1 and attention
            else "1 change needs attention"
            if attention
            else f"{active_count} unfinished changes"
            if active_count != 1 and active_count
            else "1 unfinished change"
            if active_count == 1
            else "ready"
        )
        branch = raw_values.get("BRANCH", "detached")
        landing = raw_values.get("INTEGRATION", branch)
        branch_summary = branch if landing == branch else f"{branch} → {landing}"
        configured_state = next(
            (item for item in connections if item["provider"] == effective.value), None
        )
        if configured_state and configured_state["connected"]:
            agent_state = configured_state
        elif harness == "auto":
            agent_state = next((item for item in connections if item["connected"]), None)
        else:
            agent_state = configured_state
        agent_summary = (
            f"{agent_state['provider']} — {_connection_label(agent_state)}"
            if agent_state
            else f"{effective.value} — unavailable"
        )
        add_ons: list[str] = []
        if source_count == "invalid":
            add_ons.append("invalid sources")
        elif source_count:
            add_ons.append(
                f"{source_count} grounding {'source' if source_count == 1 else 'sources'}"
            )
        if resolved.adapters.is_enabled("intent_brief"):
            add_ons.append("intent review")
        if not valid:
            next_operation = "invariant state validate"
        elif changes:
            first = next(
                (item for item in changes if item["attention"]), changes[0]
            )
            next_operation = (
                "invariant establish"
                if first["establishment"]
                else f"invariant status {first['id']}"
            )
        else:
            next_operation = 'invariant change "Describe the change"'
        lines = [f"STATUS: {status}"]
        if next_operation:
            lines.append(f"NEXT: {next_operation}")
        lines.extend(
            [
                f"BRANCH: {branch_summary}",
                f"AGENT: {agent_summary}",
                f"CHANGES: {f'{active_count} unfinished' if active_count else 'none'}",
                "ACTIVITY: foreground commands only — no background workers",
                f"ADD-ONS: {', '.join(add_ons) if add_ons else 'none'}",
            ]
        )
        for item in changes:
            lines.append(f"CHANGE: {item['label']} — {item['state']}")
            if item["detail"]:
                lines.append(f"FAILED: {item['label']} — {item['detail']}")
        if args.verbose:
            lines.extend(
                [
                    f"REPOSITORY: {repo}",
                    f"SESSION-MODE: {preferences.session_mode(repo)}",
                    "DECISION-MODE: "
                    + (
                        "agent within granted limits"
                        if resolved.authority == "agent"
                        else "ask me"
                    ),
                    "RUN-MODE: "
                    + ("automatic" if resolved.execution == "auto" else "confirm transitions"),
                ]
            )
    return CommandResult(
        lines,
        {
            "status": result,
            "harness": (
                {
                    "preference": preferences.repo_harness(repo),
                    "effective": preferences.effective_harness(repo).value,
                }
                if not args.change_id
                else None
            ),
            "connections": connections,
            "sources": source_count if not args.change_id else None,
        },
    )


def _settings(_: argparse.Namespace) -> CommandResult:
    repo = git.root()
    resolved = config.resolve(repo)
    lines = config.lines(resolved)
    settings = {
        name: value
        for line in lines
        for name, separator, value in [line.partition(": ")]
        if separator
    }
    decision_mode = {
        "agent": "agent within granted limits",
        "human": "ask me",
    }.get(settings.get("authority", ""), settings.get("authority", ""))
    run_mode = {
        "auto": "automatic",
        "assisted": "confirm transitions",
    }.get(settings.get("execution", ""), settings.get("execution", ""))
    landing_setting = settings.get("integration_branch", "auto")
    landing_resolved = settings.get("integration_branch_resolved", "")
    landing_branch = (
        f"{landing_resolved} (current branch)"
        if landing_setting == "auto"
        else landing_resolved or landing_setting
    )
    harness = preferences.repo_harness(repo)
    effective = preferences.effective_harness(repo)
    harness_source = "this clone's preference" if harness != "auto" else "machine default"
    public_lines = [
        f"HARNESS: {effective.value} — {harness_source}",
        f"SESSION-MODE: {preferences.session_mode(repo)}",
        f"DECISION-MODE: {decision_mode}",
        f"RUN-MODE: {run_mode}",
        f"LANDING-BRANCH: {landing_branch}",
        f"PUBLISHING: {'off' if settings.get('push_remote') == 'off' else 'existing upstream'}",
        f"INTENT-BRIEF: {settings.get('adapter_intent_brief', 'off')}",
    ]
    return CommandResult(
        public_lines,
        {
            "settings": {
                **settings,
                "effective_harness": effective.value,
                "session_mode": preferences.session_mode(repo),
            }
        },
    )


def _set(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    if not (repo / config.CONFIG_PATH).is_file():
        raise InvariantError(
            "Invariant: this repository is not initialized; run 'invariant init' first",
            code="not_initialized",
        )
    if args.key == "mode":
        preferences.set_session_mode(repo, args.value)
        return CommandResult(
            [f"SET: mode={args.value}"],
            {"setting": {"key": "mode", "value": args.value}},
        )
    if args.key in {"harness", "agent"}:
        preferences.set_repo_harness(repo, args.value)
        return CommandResult(
            [f"SET: harness={args.value}", "SCOPE: this clone only — not committed"],
            {"setting": {"key": "harness", "value": args.value, "scope": "local"}},
        )
    payload = _core(repo, "config", "set", args.key, args.value)
    return CommandResult(
        [f"SET: {args.key}={args.value}"],
        {
            "setting": {"key": args.key, "value": args.value},
            "protocol": payload.get("result", {}),
        },
    )


def _help(args: argparse.Namespace) -> CommandResult:
    if args.surface == "protocol":
        protocol_cli.build_parser().print_help()
    else:
        build_parser().print_help()
    return CommandResult([], {})


def run(argv: list[str] | None = None) -> int:
    values = hoist_global_options(sys.argv[1:] if argv is None else argv)
    command = _top_level_command(values)
    if command is not None and command not in PUBLIC_COMMANDS:
        return protocol_cli.run(values)
    format_name = "json" if requested_format(values) == "json" else "text"
    verbose = False
    selected_command = command or "help"
    try:
        args = build_parser().parse_args(values)
        format_name = args.format
        verbose = args.verbose
        if args.command not in {"connect", "help", "init"}:
            config.require_initialized(git.root())
        result = args.handler(args)
        if format_name == "text":
            provider_value = (
                result.data.get("provider") if isinstance(result.data, dict) else None
            )
            if (
                selected_command == "ask"
                and isinstance(provider_value, str)
                and result.data.get("invoked") is True
            ):
                rendered = style.agent_message(
                    provider_value,
                    "\n".join(result.lines),
                    heading=not result.data.get("heading_shown"),
                )
            else:
                rendered = style.render(selected_command, result.lines)
            if rendered:
                print(rendered)
            return 0
        return emit_success(selected_command, result, format_name, verbose=verbose)
    except InvariantError as exc:
        return _emit_failure(selected_command, exc, format_name, verbose)
    except Exception as exc:  # keep the envelope contract even for unexpected failures
        traceback.print_exc(file=sys.stderr)
        return _emit_failure(selected_command, internal_error(exc), format_name, verbose)


def _emit_failure(
    selected_command: str, exc: InvariantError, format_name: str, verbose: bool
) -> int:
    if format_name == "text":
        # Cause first, then the retained state and the one command that resumes it.
        print(style.error(exc.message), file=sys.stderr)
        if exc.lines:
            rendered = style.render(selected_command, exc.lines)
            if rendered:
                print(rendered)
        return exc.exit_code
    return emit_error(selected_command, exc, format_name, verbose=verbose)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
