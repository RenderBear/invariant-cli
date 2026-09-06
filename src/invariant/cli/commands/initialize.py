from __future__ import annotations

import argparse
import os
import sys
import textwrap
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Callable, Iterator

from invariant.errors import UsageError
from invariant.lifecycle import bootstrap
from invariant.mechanics import git


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("init", help="Initialize Invariant for this repository")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="use all safe defaults and configure both Codex and Claude Code",
    )
    parser.set_defaults(_handler=_initialize, _command="init")


def _color(code: str, text: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR") is not None:
        return text
    return f"\033[{code}m{text}\033[0m"


def _select(
    title: str,
    question: str,
    options: Sequence[tuple[str, str, str]],
    default: str,
) -> str:
    print(f"\n{_color('1;36', f'◆ {title}')}\n  {question}\n")
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _radio_select(options, default)
    return _line_select(options, default)


def _option_lines(
    options: Sequence[tuple[str, str, str]], selected: int, default: str
) -> list[str]:
    output: list[str] = []
    for index, (value, label, _) in enumerate(options):
        active = index == selected
        marker = "●" if active else "○"
        suffix = " (recommended)" if value == default else ""
        marker = _color("32" if active else "2", marker)
        option = _color("4", label) if active else label
        recommendation = _color("32", suffix)
        output.append(f"  {marker} {option}{recommendation}")
    output.append(_color("2", f"    {options[selected][2]}"))
    return output


def _draw(lines: Sequence[str], *, redraw: bool) -> None:
    if redraw:
        sys.stdout.write(f"\033[{len(lines)}A")
    for line in lines:
        sys.stdout.write(f"\r\033[2K{line}\n")
    sys.stdout.flush()


def _read_terminal_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            return key + msvcrt.getwch()
        return key
    key = sys.stdin.read(1)
    if key == "\x1b":
        return key + sys.stdin.read(2)
    return key


@contextmanager
def _terminal_keys() -> Iterator[Callable[[], str]]:
    if os.name == "nt":
        yield _read_terminal_key
        return
    import termios
    import tty

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        yield _read_terminal_key
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _radio_select(
    options: Sequence[tuple[str, str, str]],
    default: str,
    *,
    key_reader: Callable[[], str] | None = None,
) -> str:
    selected = next(index for index, option in enumerate(options) if option[0] == default)

    def choose(read_key: Callable[[], str]) -> str:
        nonlocal selected
        lines = _option_lines(options, selected, default)
        _draw(lines, redraw=False)
        while True:
            key = read_key()
            if key in {"\x03"}:
                raise UsageError("Invariant: initialization cancelled")
            if key in {"\x1b[A", "\x00H", "\xe0H", "k"}:
                selected = (selected - 1) % len(options)
            elif key in {"\x1b[B", "\x00P", "\xe0P", "j"}:
                selected = (selected + 1) % len(options)
            elif key in {"\r", "\n"}:
                return options[selected][0]
            else:
                continue
            lines = _option_lines(options, selected, default)
            _draw(lines, redraw=True)

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        if key_reader is not None:
            return choose(key_reader)
        with _terminal_keys() as read_key:
            return choose(read_key)
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _line_select(options: Sequence[tuple[str, str, str]], default: str) -> str:
    by_value = {value: label for value, label, _ in options}
    selected = next(index for index, option in enumerate(options) if option[0] == default)
    for line in _option_lines(options, selected, default):
        print(line)
    while True:
        try:
            answer = input(
                f"\n  {_color('36', '›')} Choice [{by_value[default]}]: "
            ).strip()
        except EOFError:
            raise UsageError(
                "Invariant: interactive initialization needs terminal input; use invariant init --defaults"
            ) from None
        if not answer:
            return default
        if answer in by_value:
            return answer
        print(_color("33", f"  Enter one of: {', '.join(by_value)}"))


def _logo() -> None:
    print()
    print(f"{_color('1;35', '╭───╮')}  {_color('1', 'INVARIANT')}")
    print(f"{_color('1;35', '│ ≡ │')}")
    print(
        f"{_color('1;35', '╰───╯')}  "
        f"{_color('2', 'Durable architectural intent for agentic work')}"
    )


def _interaction_intro(*, terminal: bool | None = None) -> None:
    if terminal is None:
        terminal = sys.stdin.isatty() and sys.stdout.isatty()
    print(f"\n{_color('1;36', 'A few things to get us started')}")
    hint = "↑/↓ navigate • enter select" if terminal else "type an option value • enter select"
    print(_color("2", f"  {hint}"))


def _interactive(repo) -> bootstrap.BootstrapSettings:
    current = git.current_branch(repo) or "detached HEAD"
    _logo()
    _interaction_intro()
    agent_choice = _select(
        "Coding agents",
        "Which agents should receive the repository workflow?",
        (
            ("both", "Codex and Claude Code", "Share one workflow through AGENTS.md."),
            ("codex", "Codex only", "Install the workflow in AGENTS.md."),
            ("claude", "Claude Code only", "Install the workflow in CLAUDE.md."),
        ),
        "both",
    )
    coding_agents = {
        "both": ("codex", "claude"),
        "codex": ("codex",),
        "claude": ("claude",),
    }[agent_choice]
    authority = _select(
        "Semantic authority",
        "Who may define repository-wide meaning, resolve contradictions, and approve durable intent?",
        (
            (
                "agent",
                "Agent authority",
                "Run governance autonomously and escalate only decisions outside the granted scope.",
            ),
            (
                "human",
                "Human review",
                "Review concise findings and choose what to investigate, adopt, or defer.",
            ),
        ),
        "agent",
    )
    execution = _select(
        "Git lifecycle",
        "How should local branch creation, verification, and landing run?",
        (
            ("auto", "Automatic", "Advance every valid and authorized local transition."),
            ("assisted", "Confirm first", "Pause before branch creation and verified landing."),
        ),
        "auto",
    )
    integration_branch = _select(
        "Integration branch",
        "Where should verified changes converge?",
        (
            ("auto", f"Current branch — {current}", "Resolve the target when each task begins."),
            ("named", "Another local branch", "Keep one fixed convergence target."),
        ),
        "auto",
    )
    if integration_branch == "named":
        try:
            integration_branch = input("\n  Branch name: ").strip()
        except EOFError:
            raise UsageError("Invariant: integration branch name is required") from None
        if not integration_branch:
            raise UsageError("Invariant: integration branch name is required")
    push_remote = _select(
        "Remote publication",
        "What should happen after a verified local landing?",
        (
            ("off", "Keep it local", "Never push unless this repository setting is changed."),
            ("on", "Publish upstream", "Push the exact commit to the branch's existing upstream."),
        ),
        "off",
    )
    task_adapter = _select(
        "Task adapter",
        "Should Invariant expand each request and validate a local acceptance contract?",
        (
            (
                "model",
                "Agent's own workflow",
                "Use the coding agent's normal understanding and the core verification lifecycle.",
            ),
            (
                "acceptance",
                "Task acceptance adapter",
                "Expand intent before work and review the exact candidate with proportional evidence.",
            ),
        ),
        "model",
    )
    return bootstrap.BootstrapSettings(
        coding_agents=coding_agents,
        authority=authority,
        execution=execution,
        integration_branch=integration_branch,
        push_remote=push_remote,
        task_acceptance=task_adapter == "acceptance",
    )


def _values(lines: list[str], name: str) -> list[str]:
    prefix = f"{name}: "
    return [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]


def _summary(lines: list[str], *, show_logo: bool) -> None:
    if show_logo:
        _logo()
    value = lambda name: (_values(lines, name) or [""])[0]
    agents = value("CODING-AGENTS")
    agent_label = {
        "codex, claude": "Codex and Claude Code",
        "codex": "Codex",
        "claude": "Claude Code",
    }.get(agents, agents)
    authority = "Human review" if value("AUTHORITY") == "human" else "Agent authority"
    execution = "Automatic" if value("EXECUTION") == "auto" else "Confirm first"
    branch = value("INTEGRATION-BRANCH")
    if value("INTEGRATION-BRANCH-SETTING") == "auto":
        branch = f"{branch} (current branch)"
    publication = "Local only" if value("PUSH-REMOTE") == "off" else "Existing upstream"
    task_adapter = (
        "Task acceptance adapter"
        if value("TASK-ACCEPTANCE-ADAPTER") == "on"
        else "Agent's own workflow"
    )

    print(f"\n{_color('1;32', '✓ Repository initialized')}\n")
    rows = (
        ("Coding agents", agent_label),
        ("Semantic authority", authority),
        ("Git lifecycle", execution),
        ("Integration", branch),
        ("Publication", publication),
        ("Task adapter", task_adapter),
        ("Configuration", value("CONFIG")),
    )
    for label, setting in rows:
        print(f"  {_color('36', f'{label:<20}')}{_color('1', setting)}")

    instructions = _values(lines, "INSTRUCTIONS")
    if instructions:
        print(f"\n{_color('1;36', '  Agent instructions')}")
        for item in instructions:
            print(f"  {_color('32', '•')} {item.removeprefix('configured ')}")

    print(f"\n{_color('1;33', 'Recommended next step')}\n")
    print("Ask your coding agent:\n")
    prompt = value("PROMPT")
    recommendation = textwrap.fill(
        prompt, width=76, initial_indent="  ", subsequent_indent="  "
    )
    print(_color("36", recommendation))


def _initialize(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    if not args.defaults and args.format == "json":
        raise UsageError("Invariant: JSON initialization requires --defaults")
    settings = bootstrap.BootstrapSettings() if args.defaults else _interactive(repo)
    lines = bootstrap.initialize(repo, settings)
    if args.format == "text":
        _summary(lines, show_logo=args.defaults)
        return []
    return lines
