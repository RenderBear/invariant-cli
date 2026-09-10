from __future__ import annotations

import argparse
import os
import sys
import textwrap
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Callable, Iterator

from invariant.cli import style
from invariant.errors import UsageError
from invariant.lifecycle import bootstrap
from invariant.mechanics import git


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("init", help="Initialize Invariant for this repository")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="use safe defaults instead of choosing repository policy",
    )
    parser.set_defaults(_handler=_initialize, _command="init")


def _color(code: str, text: str) -> str:
    return style.paint(code, text)


def _select(
    title: str,
    question: str,
    options: Sequence[tuple[str, str, str]],
    default: str,
    *,
    progress: str | None = None,
) -> str:
    if progress:
        print(f"\n{_color(style.MUTED, f'SETUP  {progress}')}")
    print(f"{_color(style.STRONG, title)}\n{question}\n")
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
        suffix = "  recommended" if value == default else ""
        marker = _color(style.ACCENT if active else style.MUTED, marker)
        option = _color(style.STRONG, label) if active else label
        recommendation = _color(style.WARN_TEXT if active else style.MUTED, suffix)
        output.append(f"  {marker} {option}{recommendation}")
        if active:
            output.append(_color(style.MUTED, f"    {options[selected][2]}"))
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
                sys.stdout.write("\n")
                sys.stdout.flush()
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
                f"\n  {style.prompt()}Choice [{by_value[default]}]: "
            ).strip()
        except EOFError:
            raise UsageError(
                "Invariant: interactive initialization needs terminal input; use invariant init --defaults"
            ) from None
        if not sys.stdin.isatty():
            print()
        if not answer:
            return default
        if answer in by_value:
            return answer
        print(_color(style.WARN_TEXT, f"  Enter one of: {', '.join(by_value)}"))


def _logo() -> None:
    print(f"\n{style.wordmark()}")
    print(_color(style.MUTED, "Scale agentic coding without architectural drift"))


def _interaction_intro(*, terminal: bool | None = None) -> None:
    if terminal is None:
        terminal = sys.stdin.isatty() and sys.stdout.isatty()
    print(f"\n{_color(style.MUTED, 'GUIDED SETUP  ·  5 choices')}")
    hint = "↑/↓ navigate • enter select" if terminal else "type an option value • enter select"
    print(_color(style.MUTED, hint))


def _interactive(
    repo, *, show_logo: bool = True
) -> bootstrap.BootstrapSettings:
    current = git.current_branch(repo) or "detached HEAD"
    if show_logo:
        _logo()
    _interaction_intro()
    authority = _select(
        "Authority",
        "Who may resolve repository-wide meaning when accepted records are insufficient?",
        (
            (
                "agent",
                "Agent decides",
                "Resolve meaning within granted limits and ask only when those limits are reached.",
            ),
            (
                "human",
                "Ask me",
                "Present concise findings when a durable repository decision is required.",
            ),
        ),
        "agent",
        progress="1/5",
    )
    execution = _select(
        "Execution",
        "How should local branch creation, verification, and landing run?",
        (
            ("auto", "Run automatically", "Advance every valid and authorized local transition."),
            ("assisted", "Pause for confirmation", "Pause before branch creation and verified landing."),
        ),
        "auto",
        progress="2/5",
    )
    integration_branch = _select(
        "Landing",
        "Where should verified changes converge?",
        (
            ("auto", f"Current branch — {current}", "Resolve the target when each task begins."),
            ("named", "Another local branch", "Keep one fixed convergence target."),
        ),
        "auto",
        progress="3/5",
    )
    if integration_branch == "named":
        try:
            integration_branch = input("\n  Branch name: ").strip()
        except EOFError:
            raise UsageError("Invariant: integration branch name is required") from None
        if not integration_branch:
            raise UsageError("Invariant: integration branch name is required")
    push_remote = _select(
        "Publishing",
        "What should happen after a verified local landing?",
        (
            ("off", "Keep it local", "Never push unless this repository setting is changed."),
            ("on", "Publish upstream", "Push the exact commit to the branch's existing upstream."),
        ),
        "off",
        progress="4/5",
    )
    task_adapter = _select(
        "Requests",
        "Should Invariant expand each request into a prose intent brief?",
        (
            (
                "model",
                "Direct",
                "Use the coding agent's normal understanding and the core verification lifecycle.",
            ),
            (
                "brief",
                "Intent brief",
                "Expand intent, ask material questions, and review the exact candidate before landing.",
            ),
        ),
        "model",
        progress="5/5",
    )
    return bootstrap.BootstrapSettings(
        authority=authority,
        execution=execution,
        integration_branch=integration_branch,
        push_remote=push_remote,
        intent_brief=task_adapter == "brief",
    )


def _values(lines: list[str], name: str) -> list[str]:
    prefix = f"{name}: "
    return [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]


def _summary(lines: list[str], *, show_recommendation: bool = True) -> None:
    value = lambda name: (_values(lines, name) or [""])[0]
    authority = "Ask me" if value("AUTHORITY") == "human" else "Agent within granted limits"
    execution = "Automatic" if value("EXECUTION") == "auto" else "Confirm first"
    branch = value("INTEGRATION-BRANCH")
    if value("INTEGRATION-BRANCH-SETTING") == "auto":
        branch = f"{branch} (current branch)"
    publication = "Local only" if value("PUSH-REMOTE") == "off" else "Existing upstream"
    task_adapter = (
        "Intent brief"
        if value("INTENT-BRIEF-ADAPTER") == "on"
        else "Agent's own workflow"
    )
    agent = {
        "auto": "Automatic",
        "codex": "Codex",
        "claude": "Claude Code",
    }.get(value("AGENT"), value("AGENT"))

    rows = (
        *([("Agent", agent)] if agent else []),
        ("Autonomy", f"{authority} · {execution}"),
        ("Landing", f"{branch} · {publication}"),
        ("Add-ons", task_adapter if task_adapter == "Intent brief" else "None"),
    )
    print(f"\n{_color(style.OK_TEXT, '  Repository ready')}\n")
    print(
        style.box(
            [f"{_color(style.MUTED, f'{label:<8}')}  {setting}" for label, setting in rows],
            tone=style.OK_TEXT,
        )
    )

    if show_recommendation:
        print(f"\n{_color(style.WARN, f'{style.NEXT} Next')}\n")
        prompt = value("PROMPT")
        recommendation = textwrap.fill(
            prompt, width=76, initial_indent="  ", subsequent_indent="  "
        )
        print(recommendation)


def establishment_choice() -> bool:
    return _select(
        "Establish records",
        "Should Invariant establish the repository's durable records now?",
        (
            (
                "yes",
                "Yes",
                "Use the selected coding agent to inspect the repository and establish its records.",
            ),
            (
                "no",
                "No",
                "Finish initialization now and run invariant establish when ready.",
            ),
        ),
        "yes",
        progress="FINAL",
    ) == "yes"


def replacement_choice() -> bool:
    _logo()
    print(f"\n{_color(style.WARN, f'{style.CAUTION} Existing configuration')}\n")
    print("This repository already has a complete Invariant configuration.")
    print("Continuing will replace every repository setting.")
    print(_color(style.MUTED, "For a single change, use invariant set <key> <value>."))
    print()
    options = (
        (
            "keep",
            "Keep current configuration",
            "Leave .invariant/config.yml unchanged.",
        ),
        (
            "replace",
            "Replace configuration",
            "Continue to guided setup and replace the complete configuration.",
        ),
    )
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _radio_select(options, "keep") == "replace"
    return _line_select(options, "keep") == "replace"


def settings(
    repo,
    *,
    defaults: bool,
    show_logo: bool = True,
) -> bootstrap.BootstrapSettings:
    if not defaults:
        return _interactive(repo, show_logo=show_logo)
    if show_logo:
        _logo()
    return bootstrap.BootstrapSettings()


def _initialize(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    if not args.defaults and args.format == "json":
        raise UsageError("Invariant: JSON initialization requires --defaults")
    selected = settings(
        repo, defaults=args.defaults, show_logo=args.format == "text"
    )
    lines = bootstrap.initialize(repo, selected)
    if args.format == "text" and getattr(args, "show_summary", True):
        _summary(
            lines,
            show_recommendation=getattr(args, "show_recommendation", True),
        )
        return []
    return lines
