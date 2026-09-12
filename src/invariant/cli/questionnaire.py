"""Keyboard-driven setup questions for the visual terminal host."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
import os
import sys
from typing import Iterator

from invariant.cli import style
from invariant.errors import UsageError

Option = tuple[str, str, str]


def intro(total: int) -> None:
    terminal = sys.stdin.isatty() and sys.stdout.isatty()
    print(f"\n{style.paint(style.MUTED, f'GUIDED SETUP  ·  {total} choices')}")
    hint = "↑/↓ navigate · enter select" if terminal else "type an option value · enter select"
    print(style.paint(style.MUTED, hint))


def select(
    title: str,
    question: str,
    options: Sequence[Option],
    default: str,
    *,
    progress: str,
) -> str:
    print(f"\n{style.paint(style.MUTED, f'SETUP  {progress}')}")
    print(f"{style.paint(style.STRONG, title)}\n{question}\n")
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _radio_select(options, default)
    return _line_select(options, default)


def _option_lines(options: Sequence[Option], selected: int, default: str) -> list[str]:
    output: list[str] = []
    for index, (value, label, description) in enumerate(options):
        active = index == selected
        marker = style.paint(style.ACCENT if active else style.MUTED, "●" if active else "○")
        shown = style.paint(style.STRONG, label) if active else label
        suffix = "  recommended" if value == default else ""
        recommendation = style.paint(style.WARN_TEXT if active else style.MUTED, suffix)
        output.append(f"  {marker} {shown}{recommendation}")
        if active:
            output.append(style.paint(style.MUTED, f"    {description}"))
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


def _radio_select(options: Sequence[Option], default: str) -> str:
    selected = next(index for index, option in enumerate(options) if option[0] == default)
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        with _terminal_keys() as read_key:
            lines = _option_lines(options, selected, default)
            _draw(lines, redraw=False)
            while True:
                key = read_key()
                if key == "\x03":
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
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def _line_select(options: Sequence[Option], default: str) -> str:
    labels = {value: label for value, label, _ in options}
    selected = next(index for index, option in enumerate(options) if option[0] == default)
    for line in _option_lines(options, selected, default):
        print(line)
    while True:
        try:
            answer = input(f"\n  {style.prompt()}Choice [{labels[default]}]: ").strip()
        except EOFError:
            raise UsageError(
                "Invariant: interactive initialization needs terminal input; "
                "use invariant init --defaults"
            ) from None
        if not sys.stdin.isatty():
            print()
        if not answer:
            return default
        if answer in labels:
            return answer
        print(style.paint(style.WARN_TEXT, f"  Enter one of: {', '.join(labels)}"))
