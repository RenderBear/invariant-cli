from __future__ import annotations

import argparse
import json
import re
import secrets
import shlex
import shutil
import subprocess
import sys
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
    connect,
    connection_status,
    invoke,
    invoke_change,
    invoke_session,
)
from invariant.harness import preferences
from invariant.lifecycle import bootstrap
from invariant.mechanics import config, git
from invariant.mechanics import governance
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
        repo, defaults=args.defaults, show_logo=not replacing
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


def _show(title: str, lines: list[str]) -> None:
    rendered = style.panel(title, lines)
    if rendered:
        print(rendered)


def _show_agent(
    provider: AgentProvider,
    message: str,
    *,
    elapsed_seconds: float | None = None,
    heading: bool = True,
) -> None:
    rendered = style.agent_message(
        provider.value, message, elapsed_seconds=elapsed_seconds, heading=heading
    )
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
    started = time.monotonic()
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
    waited = time.monotonic() - started
    session.provider_session_id = result.session_id
    response = result.response.get("message")
    if not isinstance(response, str) or not response.strip():
        raise InvariantError(
            f"Invariant: {provider.value} omitted its session response",
            code="invalid_agent_output",
        )
    if session.mode == "ask" or result.response.get("action") == "answer":
        _show_agent(
            provider, response.strip(), elapsed_seconds=waited, heading=not turn.rendered
        )
        return
    if result.response.get("action") != "change":
        raise InvariantError(
            f"Invariant: {provider.value} returned an invalid session action",
            code="invalid_agent_output",
        )
    _show_agent(
        provider, response.strip(), elapsed_seconds=waited, heading=not turn.rendered
    )
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
    rendered = style.render("change", changed.lines)
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
                        rendered = style.render("status", result.lines)
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
                        rendered = style.render("settings", result.lines)
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
                        rendered = style.render("set", result.lines)
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
                        rendered = style.render("source", result.lines)
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
                    _show("Stopped", exc.lines)
                print(style.error(exc.message), file=sys.stderr)
            if sys.stdin.isatty() and sys.stdout.isatty():
                print(style.turn_separator())
    except (EOFError, KeyboardInterrupt):
        pass
    _show("Session ended", [f"SESSIONS: {len(sessions)}"])
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
        _show("Stopped", exc.lines)
    print(style.error(exc.message), file=sys.stderr)


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
) -> dict[str, Any]:
    payload = _core(repo, "task", "finish", change_id, "--subject", subject)
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
    try:
        with style.activity("Preparing managed change", done="Prepared managed change"):
            _resolve_actions(
                repo, change_id, provider, model=args.model, timeout=args.timeout
            )
            worktree = _worktree(repo, change_id)
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
            "usage": agent.usage,
            "summary": agent.message,
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
    change_id = args.change_id or _identifier("establish", goal)
    preview = {
        "id": change_id,
        "provider": provider.value,
        "operation": "establish",
        "mode": "read-only-audit-then-managed-write",
        "invoked": False,
    }
    if args.dry_run:
        return CommandResult(
            [
                f"ESTABLISH: {change_id}",
                f"AGENT: {provider.value}",
                "MODE: inspect-then-establish",
                "STATUS: preview",
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
        if args.change_id:
            try:
                existing = _core(repo, "governance", "status", change_id)
            except Blocked as exc:
                if exc.code != "missing_task":
                    raise
        if existing is None:
            _core(repo, "governance", "begin", change_id, "--goal", goal)

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
                raise Blocked(
                    "Invariant: the repository records are ready for your decision",
                    code="authority_required",
                    lines=[
                        f"ESTABLISH: {change_id}",
                        "STATUS: needs-your-decision",
                        f"NEXT: invariant status {change_id}",
                    ],
                )

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
            with style.activity(
                f"{_provider_name(provider)} is reviewing the result",
                done=f"{_provider_name(provider)} reviewed the result",
            ):
                _resolve_actions(
                    repo, change_id, provider, model=args.model, timeout=args.timeout
                )
        task = _task(repo, change_id)
    except AgentInvocationError as exc:
        error = _identify(_agent_error(exc), "ESTABLISH", change_id)
        error.lines = [
            line for line in error.lines if not line.startswith("NEXT:")
        ]
        error.lines.append(f"NEXT: invariant establish --id {change_id}")
        raise error from exc
    except InvariantError as exc:
        error = _identify(exc, "ESTABLISH", change_id)
        if exc.code != "authority_required":
            error.lines = [
                line for line in error.lines if not line.startswith("NEXT:")
            ]
            if exc.code == "initialization_not_committed":
                error.lines.append(
                    "REQUIRES: commit the initialization on the integration branch"
                )
            error.lines.append(f"NEXT: invariant establish --id {change_id}")
        raise error
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
            "implementing": "working",
            "implementing-unborn": "working",
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
        if isinstance(task, dict):
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
        try:
            active_count = int(raw_values.get("ACTIVE-TASKS", "0"))
        except ValueError:
            active_count = 0
        status = (
            "needs attention"
            if not valid
            else f"{active_count} active changes"
            if active_count != 1 and active_count
            else "1 active change"
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
        next_operation = raw_values.get("NEXT", "")
        lines = [f"STATUS: {status}"]
        if next_operation:
            lines.append(f"NEXT: {next_operation}")
        lines.extend(
            [
                f"BRANCH: {branch_summary}",
                f"AGENT: {agent_summary}",
                f"CHANGES: {active_count if active_count else 'none'}",
                f"ADD-ONS: {', '.join(add_ons) if add_ons else 'none'}",
            ]
        )
        for item in records or []:
            if isinstance(item, dict) and item.get("name") == "TASK":
                lines.append(f"CHANGE: {item.get('value')}")
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
                    elapsed_seconds=result.data.get("elapsed_seconds"),
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
