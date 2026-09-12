"""Interactive local host for Invariant's human CLI surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
import traceback
from typing import Any

from invariant import __version__, conversation, host, observer, surface, workspace
from invariant.application import InvariantApplication
from invariant.cli import questionnaire, style
from invariant.errors import InvariantError, UsageError
from invariant.harness import preferences
from invariant.harness.providers import (
    AgentInvocationError,
    AgentProvider,
    connect,
    connection_status,
    invoke_session,
)
from invariant.mechanics import config, git
from invariant.protocol import Outcome, PROTOCOL_VERSION


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(f"Invariant: {message}")


def _provider(value: str) -> AgentProvider:
    try:
        return AgentProvider(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("choose codex or claude") from exc


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return seconds


def _hoist_format(values: list[str]) -> list[str]:
    """Accept the one global output option on either side of a subcommand."""

    hoisted: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(values):
        item = values[index]
        if item == "--format" and index + 1 < len(values):
            hoisted.extend((item, values[index + 1]))
            index += 2
            continue
        if item.startswith("--format="):
            hoisted.append(item)
        else:
            remaining.append(item)
        index += 1
    return [*hoisted, *remaining]


def build_parser() -> Parser:
    parser = Parser(
        prog="invariant",
        description="Govern meaning, run durable agent sessions, and land exact Git state",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--version", action="version", version=f"invariant {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    initialize = commands.add_parser("init", help="interactively set up this Git repository")
    initialize.add_argument("--defaults", action="store_true")

    commands.add_parser("status", help="show project sessions and governance freshness")

    start = commands.add_parser("start", help="start or resume a durable agent conversation")
    start.add_argument("prompt", nargs="?", help="optional first message")
    start.add_argument("--session", help="resume a session in this project")
    start.add_argument("--theme", help="theme for a new session")
    start.add_argument("--using", type=_provider, help="use codex or claude for this session")
    start.add_argument("--mode", choices=("ask", "change"))
    start.add_argument("--timeout", type=_positive_seconds, default=600)

    establish = commands.add_parser(
        "establish", help="draft and review a repository governance baseline"
    )
    establish.add_argument("--using", type=_provider, help="use codex or claude")
    establish.add_argument("--timeout", type=_positive_seconds, default=600)

    connection = commands.add_parser("connect", help="inspect or connect coding agents")
    connection.add_argument("provider", nargs="?", type=_provider)
    connection.add_argument("--default", dest="default_provider", type=_provider)

    setting = commands.add_parser("set", help="change one repository or clone setting")
    setting.add_argument("key")
    setting.add_argument("value")

    serve = commands.add_parser("serve", help="serve all registered projects and sessions")
    serve.add_argument("--port", type=_port, default=workspace.DEFAULT_HOST_PORT)
    serve.add_argument("--project", action="append", default=[], metavar="FOLDER")

    return parser


def _json(
    command: str,
    data: dict[str, Any],
    *,
    outcome: Outcome = Outcome.COMPLETED,
) -> None:
    print(
        json.dumps(
            {
                "protocol": PROTOCOL_VERSION,
                "command": command,
                "status": "ok",
                "outcome": outcome.value,
                "result": data,
                "diagnostics": [],
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )


def _show(command: str, lines: tuple[str, ...] | list[str], *, branded: bool = False) -> None:
    rendered = style.render(command, list(lines), branded=branded)
    if rendered:
        print(rendered)


def _initialize(args: argparse.Namespace) -> dict[str, Any]:
    repo = git.root()
    branded = True
    if config.initialized(repo):
        project = workspace.add_project(repo)
        application = InvariantApplication.bind(repo, principal=surface.USER_PRINCIPAL)
        result = {
            "project": project,
            "commit": git.resolve(repo, "HEAD"),
            "policy": config.lines(application.repository.policy),
            "unchanged": True,
        }
        lines = [
            "STATUS: unchanged",
            f"PROJECT: {project['name']}",
            f"POLICY: {config.CONFIG_PATH.as_posix()}",
            "NEXT: invariant establish",
        ]
    else:
        defaults = args.defaults or not sys.stdin.isatty()
        if not defaults:
            print(f"\n{style.wordmark('setup')}")
            questionnaire.intro(4)
            branded = False
        resolution = "secondary-agent" if defaults else questionnaire.select(
            "Resolution",
            "Who may resolve a bound semantic question?",
            (
                (
                    "secondary-agent",
                    "Secondary agent",
                    "Resolve one exact question with a scoped capability and independent run.",
                ),
                ("user", "Ask me", "Return the unresolved question for direct user authority."),
            ),
            "secondary-agent",
            progress="1/4",
        )
        transitions = "auto" if defaults else questionnaire.select(
            "Execution",
            "How should authorized local lifecycle transitions proceed?",
            (
                ("auto", "Run automatically", "Advance valid, authorized local transitions."),
                ("assisted", "Pause for confirmation", "Pause between lifecycle consequences."),
            ),
            "auto",
            progress="2/4",
        )
        publication = "off" if defaults else questionnaire.select(
            "Publication",
            "May an explicitly granted publication capability use the existing upstream?",
            (
                ("off", "Keep it local", "Never push unless this policy is changed."),
                ("on", "Allow upstream", "Permit only the exact commit and existing upstream."),
            ),
            "off",
            progress="3/4",
        )
        harness = "auto" if defaults else questionnaire.select(
            "Agent",
            "Which connected coding agent should new sessions prefer?",
            (
                ("auto", "Choose automatically", "Use the first connected native agent."),
                ("codex", "Codex", "Use the local Codex installation."),
                ("claude", "Claude Code", "Use the local Claude Code installation."),
            ),
            "auto",
            progress="4/4",
        )
        initialized = InvariantApplication.initialize(
            repo,
            resolution_delegation=resolution,
            execution_transitions=transitions,
            publication=publication,
        )
        preferences.set_repo_harness(repo, harness)
        project = workspace.add_project(repo)
        result = {**initialized.result, "project": project, "unchanged": False}
        lines = [
            "STATUS: ready",
            f"PROJECT: {project['name']}",
            "INTENT: user",
            f"RESOLUTION: {resolution}",
            f"EXECUTION: parallel work · {transitions} transitions",
            "LIFECYCLE: Git-grounded",
            f"HARNESS: {harness}",
            f"POLICY: {config.CONFIG_PATH.as_posix()} @ {str(initialized.result['commit'])[:12]}",
            "NEXT: invariant establish",
        ]
    if args.format == "json":
        _json("init", result)
    else:
        _show("init", lines, branded=branded)
    return result


def _status(repo: Path, *, format_name: str = "text") -> dict[str, Any]:
    project = workspace.add_project(repo)
    snapshot = observer.build_snapshot(repo)
    sessions = workspace.list_sessions(project_id=str(project["id"]))
    audit = snapshot.get("governance", {}).get("audit", {})
    live = sum(1 for session in sessions if session.get("live"))
    behind = audit.get("behind")
    staleness = str(audit.get("status") or "absent")
    if isinstance(behind, int) and behind:
        staleness += f" · {behind} commits behind"
    repository = snapshot.get("repository", {})
    record_count = len(snapshot.get("governance", {}).get("records", []))
    lines = [
        f"STATUS: {repository.get('state', 'unknown')}",
        f"PROJECT: {project['name']}",
        f"BRANCH: {repository.get('branch', '—')}",
        f"SESSIONS: {len(sessions)} total · {live} live",
        f"INTENT: {repository.get('intent') or repository.get('authority') or '—'}",
        f"RESOLUTION: {repository.get('resolution', '—')}",
        "SEMANTIC-KERNEL: "
        f"{record_count} accepted records",
        "EXECUTION: parallel work · "
        f"{repository.get('execution', '—')} transitions · max {repository.get('parallelism', '—')}",
        "LIFECYCLE: Git-grounded",
        f"STALENESS: {staleness}",
        "LAST-AUDIT: "
        + (
            f"{audit.get('id')} · {audit.get('created_at')}"
            if audit.get("id")
            else "none"
        ),
    ]
    for session in sessions[:5]:
        live_mark = " · live" if session.get("live") else ""
        lines.append(
            f"SESSION: {session['id']} · {session['theme']} · "
            f"{session.get('provider') or 'unassigned'}{live_mark}"
        )
    if record_count == 0:
        lines.append("NEXT: invariant establish")
    data = {"project": project, "sessions": sessions, "snapshot": snapshot}
    if format_name == "json":
        _json("status", data)
    else:
        _show("status", lines)
    return data


def _connect(args: argparse.Namespace) -> dict[str, Any]:
    requested = args.default_provider or args.provider
    if args.default_provider and args.provider and args.default_provider != args.provider:
        raise UsageError("Invariant: provider and --default must name the same agent")
    if requested is not None:
        try:
            connect(requested)
        except AgentInvocationError as error:
            raise InvariantError(
                f"Invariant: {error.message}", code=error.code, lines=error.lines
            ) from error
        if args.default_provider:
            preferences.set_default_harness(requested)
    states = [connection_status(provider) for provider in AgentProvider]
    default = preferences.default_harness()
    lines = [f"DEFAULT: {default.value}"]
    for state in states:
        condition = "connected" if state.authenticated else (
            "installed" if state.installed else "unavailable"
        )
        lines.append(f"AGENT: {state.provider.value} · {condition} · {state.version or '—'}")
        if state.hint:
            lines.append(f"OPTION: {state.hint}")
    data = {
        "default": default.value,
        "providers": [
            {
                "provider": state.provider.value,
                "installed": state.installed,
                "authenticated": state.authenticated,
                "version": state.version,
                "hint": state.hint,
            }
            for state in states
        ],
    }
    if args.format == "json":
        _json("connect", data)
    else:
        _show("connect", lines)
    return data


def _set(args: argparse.Namespace) -> dict[str, Any]:
    repo = git.root()
    with style.activity("Applying governed setting", done="Setting landed"):
        result = surface.set_value(repo, args.key, args.value)
    if args.format == "json":
        _json("set", result.data)
    else:
        _show("set", result.lines)
    return result.data


def _select_session_provider(
    repo: Path, selected: dict[str, Any], requested: AgentProvider | None
) -> AgentProvider:
    if requested is not None:
        return conversation.resolve_provider(repo, requested)
    saved = str(selected.get("provider") or "")
    if saved:
        try:
            return conversation.resolve_provider(repo, AgentProvider(saved))
        except (ValueError, InvariantError):
            pass
    return conversation.resolve_provider(repo)


def _session_lines(sessions: list[dict[str, Any]], active_id: str) -> list[str]:
    lines: list[str] = []
    for index, session in enumerate(sessions, 1):
        active = " · current" if session["id"] == active_id else ""
        lines.append(
            f"SESSION: {index} · {session['id']} · {session['theme']} · "
            f"{session.get('provider') or 'unassigned'}{active}"
        )
    return lines or ["STATUS: no sessions"]


def _session_error(error: InvariantError) -> None:
    print(style.error(error.message), file=sys.stderr)
    for line in error.lines:
        print(line, file=sys.stderr)


def _start(args: argparse.Namespace) -> dict[str, Any]:
    repo = git.root()
    if not config.initialized(repo):
        _initialize(argparse.Namespace(defaults=not sys.stdin.isatty(), format="text"))
    project = workspace.add_project(repo)
    if args.session:
        selected = workspace.require_session_project(args.session, repo)
    else:
        selected = workspace.new_session(
            repo,
            args.theme or (args.prompt[:80] if args.prompt else "New session"),
            mode=args.mode or preferences.session_mode(repo),
            provider=args.using.value if args.using else "",
        )
    if args.mode and selected.get("mode") != args.mode:
        selected = workspace.update_session(str(selected["id"]), mode=args.mode)
    provider = _select_session_provider(repo, selected, args.using)
    private = workspace.session_private(str(selected["id"]))
    if str(selected.get("provider") or "") != provider.value:
        selected = workspace.update_session(
            str(selected["id"]), provider=provider.value, provider_session_id=""
        )
        private["provider_session_id"] = ""
    else:
        workspace.update_session(str(selected["id"]), provider=provider.value)

    active_id = str(selected["id"])
    workspace.mark_session_live(active_id, surface="console")
    print(style.session_intro(provider.value, str(selected["mode"]), active_id))
    pending = args.prompt or ""
    try:
        while True:
            selected = workspace.session(active_id)
            mode = str(selected.get("mode") or "change")
            if pending:
                message, pending = pending, ""
            elif sys.stdin.isatty():
                message = input(style.prompt(mode)).strip()
                redrawn = style.redraw_user_line(message, mode) if message else None
                if redrawn:
                    print(redrawn)
            else:
                raw = sys.stdin.readline()
                if raw == "":
                    break
                message = raw.strip()
            if not message:
                continue
            establishing = False
            transcript_message = message
            if message.startswith(":"):
                control, _, control_value = message[1:].partition(" ")
                if control.lower() == "establish":
                    establishing = True
                    transcript_message = message
                    message = conversation.establishment_intent(control_value)
            if message.startswith(":") and not establishing:
                command, _, raw_value = message[1:].partition(" ")
                command, raw_value = command.lower(), raw_value.strip()
                if command in {"exit", "quit"}:
                    break
                if command == "help":
                    _show(
                        "status",
                        [
                            "COMMAND: :new [theme] · create and enter a session",
                            "COMMAND: :sessions · list project sessions",
                            "COMMAND: :switch ID|N · switch sessions",
                            "COMMAND: :agent codex|claude · switch this session's agent",
                            "COMMAND: :mode ask|change · change conversation mode",
                            "COMMAND: :status · show sessions and governance freshness",
                            "COMMAND: :settings · show current settings",
                            "COMMAND: :set KEY VALUE · apply one setting",
                            "COMMAND: :establish [focus] · draft a governance baseline",
                            "COMMAND: :details [CHANGE] · inspect a pending governance proposal",
                            "COMMAND: :accept [CHANGE] · accept when resolution is human",
                            "COMMAND: :exit · preserve the session and leave",
                        ],
                    )
                    continue
                if command == "new":
                    workspace.clear_session_live(active_id)
                    selected = workspace.new_session(
                        repo,
                        raw_value or "New session",
                        mode=mode,
                        provider=provider.value,
                    )
                    active_id = str(selected["id"])
                    workspace.mark_session_live(active_id, surface="console")
                    private = workspace.session_private(active_id)
                    print(style.session_intro(provider.value, mode, active_id))
                    continue
                if command == "sessions":
                    sessions = workspace.list_sessions(project_id=str(project["id"]))
                    _show("status", _session_lines(sessions, active_id))
                    continue
                if command == "switch":
                    sessions = workspace.list_sessions(project_id=str(project["id"]))
                    identifier = raw_value
                    if raw_value.isdigit() and 1 <= int(raw_value) <= len(sessions):
                        identifier = str(sessions[int(raw_value) - 1]["id"])
                    try:
                        selected = workspace.require_session_project(identifier, repo)
                        next_provider = _select_session_provider(repo, selected, None)
                    except InvariantError as error:
                        _session_error(error)
                        continue
                    next_id = str(selected["id"])
                    private = workspace.session_private(next_id)
                    if str(selected.get("provider") or "") != next_provider.value:
                        selected = workspace.update_session(
                            next_id,
                            provider=next_provider.value,
                            provider_session_id="",
                        )
                        private["provider_session_id"] = ""
                    workspace.clear_session_live(active_id)
                    active_id = next_id
                    provider = next_provider
                    workspace.mark_session_live(active_id, surface="console")
                    print(style.session_intro(provider.value, str(selected["mode"]), active_id))
                    continue
                if command == "agent":
                    try:
                        provider = conversation.resolve_provider(repo, AgentProvider(raw_value))
                    except ValueError as exc:
                        _session_error(UsageError("Invariant: use :agent codex|claude"))
                        continue
                    except InvariantError as error:
                        _session_error(error)
                        continue
                    workspace.update_session(
                        active_id, provider=provider.value, provider_session_id=""
                    )
                    private["provider_session_id"] = ""
                    _show("settings", [f"AGENT: {provider.value}", f"SESSION: {active_id}"])
                    continue
                if command == "mode":
                    if raw_value not in {"ask", "change"}:
                        _session_error(UsageError("Invariant: use :mode ask|change"))
                        continue
                    workspace.update_session(active_id, mode=raw_value)
                    _show("settings", [f"MODE: {raw_value}", f"SESSION: {active_id}"])
                    continue
                if command == "status":
                    _status(repo)
                    continue
                if command == "settings":
                    _show("settings", surface.settings(repo).lines)
                    continue
                if command == "set":
                    try:
                        values = shlex.split(raw_value)
                    except ValueError as error:
                        _session_error(UsageError(f"Invariant: {error}"))
                        continue
                    if len(values) != 2:
                        _session_error(UsageError("Invariant: use :set KEY VALUE"))
                        continue
                    try:
                        result = surface.set_value(repo, values[0], values[1])
                    except InvariantError as error:
                        _session_error(error)
                        continue
                    _show("set", result.lines)
                    if values[0] == "harness":
                        try:
                            provider = conversation.resolve_provider(repo)
                        except InvariantError as error:
                            _session_error(error)
                            continue
                        workspace.update_session(
                            active_id, provider=provider.value, provider_session_id=""
                        )
                        private["provider_session_id"] = ""
                    continue
                if command == "accept":
                    change_id = raw_value or str(selected.get("pending_change") or "")
                    if not change_id:
                        _session_error(
                            UsageError("Invariant: no pending change; use :accept CHANGE")
                        )
                        continue
                    try:
                        result = surface.accept_pending(repo, change_id)
                    except InvariantError as error:
                        _session_error(error)
                        continue
                    workspace.update_session(
                        active_id, pending_change="", pending_action=""
                    )
                    _show("change", result.lines)
                    continue
                if command == "details":
                    change_id = raw_value or str(selected.get("pending_change") or "")
                    if not change_id:
                        _session_error(
                            UsageError("Invariant: no pending change; use :details CHANGE")
                        )
                        continue
                    try:
                        result = surface.pending_details(repo, change_id)
                    except InvariantError as error:
                        _session_error(error)
                        continue
                    print(style.decision("Governance candidate details", result.lines))
                    continue
                _show("status", [f"INVALID: unknown session command ':{command}'"])
                continue

            workspace.append_message(active_id, "user", transcript_message)
            change_result: surface.SurfaceResult | None = None
            try:
                turn_mode = "change" if establishing else mode
                decision_context = ""
                pending_change = str(selected.get("pending_change") or "")
                if pending_change and not establishing:
                    try:
                        pending_details = surface.pending_details(repo, pending_change)
                    except InvariantError:
                        workspace.update_session(
                            active_id, pending_change="", pending_action=""
                        )
                    else:
                        decision_context = "\n".join(pending_details.lines)
                with style.turn(provider.value) as activity:
                    reply = invoke_session(
                        provider,
                        repo,
                        conversation.prompt(
                            repo,
                            turn_mode,
                            message,
                            decision_context=decision_context,
                        ),
                        conversation.schema(turn_mode),
                        session_id=str(private.get("provider_session_id") or "") or None,
                        timeout=args.timeout,
                    )
                private["provider_session_id"] = reply.session_id
                workspace.update_session(
                    active_id,
                    provider=provider.value,
                    provider_session_id=reply.session_id,
                )
                answer = str(reply.response.get("message") or "").strip()
                if turn_mode == "change" and reply.response.get("action") == "change":
                    with style.activity(
                        (
                            f"{provider.value.capitalize()} is drafting the governance baseline"
                            if establishing
                            else f"{provider.value.capitalize()} is implementing the change"
                        ),
                        done=(
                            f"{provider.value.capitalize()} drafted the governance baseline"
                            if establishing
                            else f"{provider.value.capitalize()} implemented the candidate"
                        ),
                    ):
                        result = surface.execute_agent_change(
                            repo,
                            provider,
                            active_id,
                            message,
                            (
                                [".invariant/records", ".invariant/audits"]
                                if establishing
                                else [
                                    str(path)
                                    for path in reply.response.get("paths", [])
                                ]
                            ),
                            timeout=args.timeout,
                        )
                    change_result = result
                    if result.data.get("pending"):
                        workspace.update_session(
                            active_id,
                            pending_change=str(result.data["change"]),
                            pending_action=str(result.data["action"]["id"]),
                        )
                    else:
                        workspace.update_session(
                            active_id, pending_change="", pending_action=""
                        )
                    governance = result.data.get("governance")
                    details = "\n".join(result.lines)
                    if governance is not None:
                        answer = (
                            "The governance proposal is ready for your decision."
                            if result.data.get("pending")
                            else "The governance baseline was independently resolved and landed."
                        )
                    else:
                        answer = "\n\n".join(
                            filter(None, [answer, result.data.get("message", "")])
                        )
                    if not result.data.get("pending"):
                        answer = "\n\n".join(filter(None, [answer, details]))
                transcript_answer = answer
                if change_result is not None and change_result.data.get("pending"):
                    transcript_answer = "\n\n".join(
                        filter(None, [answer, "\n".join(change_result.lines)])
                    )
                workspace.append_message(active_id, "assistant", transcript_answer)
                print(style.agent_message(provider.value, answer, heading=not activity.rendered))
                if change_result is not None and change_result.data.get("pending"):
                    print(
                        style.decision(
                            str(
                                change_result.data.get("decision_title")
                                or "Decision required"
                            ),
                            change_result.lines,
                        )
                    )
                if style.interactive():
                    print(style.turn_separator())
            except AgentInvocationError as error:
                failure = f"{provider.value}: {error.message}"
                workspace.append_message(active_id, "assistant", failure, state="failed")
                print(style.error(f"Invariant: {failure}"), file=sys.stderr)
            except InvariantError as error:
                workspace.append_message(active_id, "system", error.message, state="failed")
                print(style.error(error.message), file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        workspace.clear_session_live(active_id)
        print(style.session_outro())
    return {"project": project, "session": workspace.session(active_id)}


def _establish(args: argparse.Namespace) -> dict[str, Any]:
    if args.format == "json":
        raise UsageError("Invariant: establish is an interactive text command")
    return _start(
        argparse.Namespace(
            prompt=":establish",
            session=None,
            theme="Governance baseline",
            using=args.using,
            mode="change",
            timeout=args.timeout,
        )
    )


def _serve(args: argparse.Namespace) -> None:
    if args.format == "json":
        raise UsageError("Invariant: serve is a foreground text command")
    for folder in args.project:
        workspace.add_project(Path(folder))
    if not workspace.list_projects():
        try:
            repo = git.root()
        except InvariantError:
            repo = None
        if repo is not None and config.initialized(repo):
            workspace.add_project(repo)
    address = f"http://127.0.0.1:{args.port}"
    _show(
        "status",
        [
            f"ADDRESS: {address}",
            "ACCESS: read-only · loopback only",
            "STATE: this user's registered projects",
            "PROJECTS: all registered repositories",
            "SESSIONS: live presence and durable transcripts",
            "LIFETIME: until this process stops",
        ],
    )
    host.serve(args.port)


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        values = list(sys.argv[1:] if argv is None else argv)
        args = parser.parse_args(_hoist_format(values))
        if args.command == "init":
            _initialize(args)
        elif args.command == "status":
            _status(git.root(), format_name=args.format)
        elif args.command == "connect":
            _connect(args)
        elif args.command == "set":
            _set(args)
        elif args.command == "establish":
            _establish(args)
        elif args.command == "start":
            if args.format == "json":
                raise UsageError("Invariant: start is an interactive text command")
            _start(args)
        else:
            _serve(args)
        return 0
    except InvariantError as error:
        if "args" in locals() and getattr(args, "format", "text") == "json":
            print(
                json.dumps(
                    {
                        "protocol": PROTOCOL_VERSION,
                        "command": getattr(args, "command", "unknown"),
                        "status": "blocked" if error.exit_code == 1 else "error",
                        "outcome": (
                            Outcome.BLOCKED.value
                            if error.exit_code == 1
                            else Outcome.FAILED.value
                        ),
                        "result": error.data or {},
                        "diagnostics": [{"code": error.code, "message": error.message}],
                    },
                    separators=(",", ":"),
                )
            )
        else:
            print(style.error(error.message), file=sys.stderr)
            for line in error.lines:
                print(line, file=sys.stderr)
        return error.exit_code
    except Exception as error:
        message = f"Invariant: internal failure — {type(error).__name__}: {error}"
        if "args" in locals() and getattr(args, "format", "text") == "json":
            print(
                json.dumps(
                    {
                        "protocol": PROTOCOL_VERSION,
                        "command": getattr(args, "command", "unknown"),
                        "status": "error",
                        "outcome": Outcome.FAILED.value,
                        "result": {},
                        "diagnostics": [
                            {"code": "internal_failure", "message": message}
                        ],
                    },
                    separators=(",", ":"),
                )
            )
        else:
            traceback.print_exc(file=sys.stderr)
            print(style.error(message), file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(run())
