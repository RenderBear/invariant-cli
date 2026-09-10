"""Terminal presentation for the human-facing command surface.

One accent, and it belongs to the wordmark: `Invariant` is the only bold, coloured thing in a
result block, so it reads a size larger than everything around it. Titles, labels, rules, and
hints are dim; values are plain; state words carry one of three tones. Structure comes from
alignment and whitespace, never from borders or banners. Everything degrades to the plain
`NAME: value` records when output is not a terminal.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
import threading
import time
from collections.abc import Sequence
from typing import TextIO

# Palette — ANSI attributes so the user's terminal theme supplies the actual colours.
ACCENT = "1;36"
STRONG = "1"
MUTED = "2"
OK = "1;32"
OK_TEXT = "32"
WARN = "1;33"
WARN_TEXT = "33"
BAD = "1;31"

# Glyphs — each one is reserved for a single meaning.
CHECK = "✓"
CROSS = "×"
CAUTION = "!"
NEXT = "→"
PROMPT = "›"
RULE = "─"
DOT = "·"

_TITLES = {
    "ask": "Answer",
    "change": "Change landed",
    "connect": "Connections",
    "establish": "Records established",
    "init": "Repository ready",
    "set": "Setting updated",
    "settings": "Settings",
    "source": "Grounding source added",
    "status": "Repository",
}

_SUCCESS_COMMANDS = {"change", "establish", "init", "set", "source"}
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_OK_STATES = {"complete", "completed", "ready", "valid", "landed", "connected", "on", "fresh"}
_WAIT_STATES = {
    "blocked",
    "waiting",
    "needs attention",
    "needs-your-decision",
    "awaiting-review",
    "awaiting-landing",
    "awaiting-branch",
    "implementing",
    "briefing",
    "paused",
    "planning",
    "working",
    "reviewing",
    "checking",
    "preview",
}
_BAD_STATES = {"failed", "error", "invalid", "stale", "unavailable", "absent"}

_CALLOUTS = {
    "Next": (ACCENT, NEXT),
    "Warning": (WARN, CAUTION),
    "Error": (BAD, CROSS),
    "Invalid": (BAD, CROSS),
    "Request": (ACCENT, PROMPT),
    "Command": (ACCENT, PROMPT),
}


def paint(code: str, text: str, *, stream: TextIO | None = None) -> str:
    target = stream or sys.stdout
    if not target.isatty() or os.environ.get("NO_COLOR") is not None:
        return text
    return f"\033[{code}m{text}\033[0m"


def interactive(stream: TextIO | None = None) -> bool:
    return (stream or sys.stdout).isatty()


def columns(stream: TextIO | None = None) -> int:
    target = stream or sys.stdout
    try:
        width = os.get_terminal_size(target.fileno()).columns
    except (AttributeError, OSError, ValueError):
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
    # Pseudo-terminals without a window size report 0 or a handful of columns.
    return width if width >= 24 else 80


def wordmark(subtitle: str | None = None, *, tone: str = MUTED) -> str:
    """`Invariant` in the accent, then the context in a quiet tone two spaces to the right."""

    mark = paint(ACCENT, "Invariant")
    if not subtitle:
        return mark
    return f"{mark}  {paint(tone, subtitle)}"


def prompt(mode: str = "ask") -> str:
    """The user's prompt names the session mode: `(ask) › ` or `(change) › `."""

    return f"{paint(MUTED, f'({mode})')} {paint(ACCENT, PROMPT)} "


def speaker(name: str) -> str:
    """The agent's line mirrors the prompt with its provider name: `(codex) ›`."""

    return f"{paint(ACCENT, f'({name})')} {paint(ACCENT, PROMPT)}"


def elapsed(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest:02d}s"


PROSE_MEASURE = 88
TURN_RULE_WIDTH = 24

_INLINE_STRONG = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
_LIST_INDENT = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)")


def measure(stream: TextIO | None = None) -> int:
    return min(PROSE_MEASURE, columns(stream) - 4)


def _inline(text: str) -> str:
    return _INLINE_STRONG.sub(
        lambda match: paint(STRONG, match.group(1) or match.group(2)), text
    )


def prose(text: str, *, width: int | None = None) -> list[str]:
    """Lay out agent prose for reading: a measure, bold emphasis, code kept verbatim."""

    limit = width or measure()
    output: list[str] = []
    fenced = False
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            output.append(f"    {line}" if line else "")
            continue
        if not stripped:
            output.append("")
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", stripped)
        if heading:
            output.append(f"  {paint(STRONG, heading.group(1))}")
            continue
        indent = _LIST_INDENT.match(line)
        hang = " " * len(indent.group(1)) if indent else ""
        wrapped = textwrap.wrap(
            line.rstrip(),
            width=limit,
            initial_indent="  ",
            subsequent_indent=f"  {hang}",
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        output.extend(_inline(item) for item in wrapped)
    return output


def user_line(message: str, mode: str = "ask") -> str:
    return f"{prompt(mode)}{message}"


def redraw_user_line(
    message: str, mode: str = "ask", stream: TextIO | None = None
) -> str | None:
    """Replace the raw input line with the styled one, if it fits on one physical line."""

    target = stream or sys.stdout
    if not interactive(target) or len(mode) + len(message) + 5 >= columns(target):
        return None
    return f"\033[1A\r\033[2K{user_line(message, mode)}"


def turn_separator() -> str:
    # The agent block already ends with a blank line; the rule adds only its own trailing one.
    return f"  {paint(MUTED, RULE * TURN_RULE_WIDTH)}\n"


def agent_message(
    name: str,
    message: str,
    *,
    terminal: bool | None = None,
    elapsed_seconds: float | None = None,
    heading: bool = True,
) -> str:
    """Render agent prose as conversation, not as an Invariant result panel."""

    content = message.strip()
    if terminal is None:
        terminal = interactive()
    if not terminal:
        return content
    body = "\n".join(prose(content))
    # The final newline becomes deliberate breathing room when the caller prints the block.
    if not heading:
        return f"{body}\n"
    head = speaker(name)
    if elapsed_seconds is not None:
        head += f" {paint(MUTED, elapsed(elapsed_seconds))}"
    return f"{head}\n{body}\n"


def session_intro(name: str, mode: str, identifier: int) -> str:
    if not interactive():
        return "\n".join(
            [
                f"SESSION: {identifier}",
                f"HARNESS: {name.lower().removesuffix(' code')}",
                f"MODE: {mode}",
                "TIP: :help shows session commands; Ctrl-C ends this console",
            ]
        )
    separator = f"  {paint(MUTED, DOT)}  "
    context = separator.join(
        [paint(ACCENT, name), f"{mode} mode", f"session {identifier}"]
    )
    return "\n".join(
        [
            wordmark("conversation"),
            f"  {context}",
            paint(MUTED, f"  :help for commands  {DOT}  Ctrl-C to leave"),
            "",
        ]
    )


def animation_enabled(stream: TextIO | None = None) -> bool:
    target = stream or sys.stderr
    disabled = os.environ.get("INVARIANT_NO_ANIMATION", "").strip().lower()
    return (
        interactive()
        and interactive(target)
        and disabled not in {"1", "true", "yes", "on"}
        and os.environ.get("TERM", "") != "dumb"
        and os.environ.get("CI") is None
    )


class Activity:
    """A transient spinner that leaves one settled line behind when the step finishes.

    The trail turns a long-running command into a visible sequence of completed stages with
    their durations, which is what makes waiting on an agent feel like progress rather than
    silence. It is suppressed wherever animation is.
    """

    def __init__(
        self,
        label: str,
        *,
        done: str | None = None,
        stream: TextIO | None = None,
        enabled: bool | None = None,
        interval: float = 0.08,
        trail: bool = True,
    ) -> None:
        self.label = label.strip()
        self.done = (done or self.label).strip()
        self.stream = stream or sys.stderr
        self.enabled = animation_enabled(self.stream) if enabled is None else enabled
        self.interval = interval
        self.trail = trail
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = 0.0

    def _line(self, frame: str) -> str:
        width = columns(self.stream)
        value = f"{frame} {self.label}"
        waited = time.monotonic() - self._started
        if waited >= 3:
            value += f" {DOT} {elapsed(waited)}"
        if len(value) >= width:
            value = f"{value[: max(1, width - 2)].rstrip()}…"
        return paint(MUTED, value, stream=self.stream)

    def _draw(self, frame: str) -> None:
        self.stream.write(f"\r\033[2K{self._line(frame)}")
        self.stream.flush()

    def _animate(self) -> None:
        index = 1
        while not self._stop.wait(self.interval):
            self._draw(_SPINNER_FRAMES[index % len(_SPINNER_FRAMES)])
            index += 1

    def __enter__(self) -> Activity:
        self._started = time.monotonic()
        if self.enabled:
            self._draw(_SPINNER_FRAMES[0])
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type: object, *_exc: object) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.2, self.interval * 2))
        self.stream.write("\r\033[2K")
        if self.trail:
            waited = elapsed(time.monotonic() - self._started)
            if exc_type is None:
                mark = paint(OK_TEXT, CHECK, stream=self.stream)
                label = self.done
            else:
                mark = paint(BAD, CROSS, stream=self.stream)
                label = self.label
            self.stream.write(f"{mark} {label} {paint(MUTED, f'{DOT} {waited}', stream=self.stream)}\n")
        self.stream.flush()


def activity(
    label: str,
    *,
    done: str | None = None,
    stream: TextIO | None = None,
    enabled: bool | None = None,
    interval: float = 0.08,
    trail: bool = True,
) -> Activity:
    return Activity(
        label, done=done, stream=stream, enabled=enabled, interval=interval, trail=trail
    )


class Turn(Activity):
    """The agent's own line while it works: `(codex) › thinking ⠹`, settling to `(codex) › 4.2s`.

    It lives on standard output because it is part of the transcript, not a status aside.
    """

    def __init__(self, name: str, *, stream: TextIO | None = None, enabled: bool | None = None) -> None:
        super().__init__("thinking", stream=stream or sys.stdout, enabled=enabled, trail=True)
        self.name = name
        self.rendered = False

    def _line(self, frame: str) -> str:
        waited = time.monotonic() - self._started
        detail = f"thinking {frame}"
        if waited >= 3:
            detail += f" {DOT} {elapsed(waited)}"
        return f"{speaker(self.name)} {paint(MUTED, detail, stream=self.stream)}"

    def __exit__(self, exc_type: object, *_exc: object) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.2, self.interval * 2))
        waited = paint(MUTED, elapsed(time.monotonic() - self._started), stream=self.stream)
        mark = "" if exc_type is None else f"{paint(BAD, CROSS, stream=self.stream)} "
        self.stream.write(f"\r\033[2K{speaker(self.name)} {mark}{waited}\n")
        self.stream.flush()
        self.rendered = True


def turn(name: str, *, stream: TextIO | None = None, enabled: bool | None = None) -> Turn:
    return Turn(name, stream=stream, enabled=enabled)


def _label(raw: str) -> str:
    return {"ADD-ONS": "Add-ons"}.get(raw, raw.replace("-", " ").capitalize())


def _state(value: str) -> str:
    lowered = value.lower()
    if lowered in _OK_STATES:
        return paint(OK_TEXT, value)
    if lowered in _WAIT_STATES:
        return paint(WARN_TEXT, value)
    if lowered in _BAD_STATES:
        return paint(BAD, value)
    return value


def panel(title: str | None, lines: Sequence[str], *, success: bool = False) -> str:
    """Render records as an aligned block: wordmark line, fields, then closing callouts."""

    values = list(lines)
    if not interactive():
        return "\n".join(values)

    fields: list[tuple[str, str] | str] = []
    callouts: list[tuple[str, str]] = []
    width = 0
    for line in values:
        match = re.match(r"^([A-Z][A-Z0-9-]*): (.*)$", line)
        if not match:
            fields.append(line)
            continue
        label = _label(match.group(1))
        if label in _CALLOUTS:
            callouts.append((label, match.group(2)))
            continue
        width = max(width, len(label))
        fields.append((label, match.group(2)))

    output = [wordmark(title, tone=OK_TEXT if success else MUTED)]
    previous = ""
    for field in fields:
        if isinstance(field, str):
            output.append(field)
            previous = ""
            continue
        label, value = field
        if label in {"Status"}:
            value = _state(value)
        shown = "" if label == previous else label
        output.append(f"  {paint(MUTED, f'{shown:<{width}}')}  {value}")
        previous = label
    if callouts:
        if fields:
            output.append("")
        for label, value in callouts:
            tone, glyph = _CALLOUTS[label]
            output.append(f"  {paint(tone, glyph)} {value}")
    return "\n".join(output)


def render(command: str, lines: Sequence[str]) -> str:
    if not lines:
        return ""
    title = _TITLES.get(command)
    if command == "init" and "STATUS: unchanged" in lines:
        title = "Configuration unchanged"
    if command == "change" and not any(line == "STATUS: complete" for line in lines):
        title = "Change"
    if command == "establish" and not any(line == "STATUS: complete" for line in lines):
        title = "Repository records"
    return panel(
        title,
        lines,
        success=command in _SUCCESS_COMMANDS and title in _TITLES.values(),
    )


def error(message: str) -> str:
    if not interactive(sys.stderr):
        return message
    detail = message.removeprefix("Invariant: ")
    return f"{paint(BAD, CROSS, stream=sys.stderr)} {detail}"
