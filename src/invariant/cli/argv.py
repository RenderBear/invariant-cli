from __future__ import annotations

from typing import Iterable


def requested_format(argv: Iterable[str]) -> str:
    """Read the output format before parsing so even a usage error honours it."""

    values = list(argv)
    for index, item in enumerate(values):
        if item == "--":
            break
        if item == "--format" and index + 1 < len(values):
            return values[index + 1]
        if item.startswith("--format="):
            return item.partition("=")[2]
    return "text"


def hoist_global_options(
    argv: Iterable[str],
    *,
    valued: Iterable[str] = ("--format",),
    flags: Iterable[str] = ("--verbose",),
) -> list[str]:
    """Move global options to the front so they are accepted after a subcommand too."""

    valued_names = set(valued)
    flag_names = set(flags)
    hoisted: list[str] = []
    remaining: list[str] = []
    values = list(argv)
    index = 0
    while index < len(values):
        item = values[index]
        if item == "--":
            remaining.extend(values[index:])
            break
        name, separator, inline = item.partition("=")
        if name in valued_names:
            if separator:
                hoisted.append(item)
            elif index + 1 < len(values):
                hoisted.extend([item, values[index + 1]])
                index += 1
            else:
                remaining.append(item)
        elif item in flag_names:
            hoisted.append(item)
        else:
            remaining.append(item)
        index += 1
    return [*hoisted, *remaining]
