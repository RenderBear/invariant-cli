"""Host-side authentication of the user principal.

The kernel is a library, so the process that binds it is the transport. A ``user:`` principal is
accepted only when the binding process can show that a person, not a provider run, is driving it.
The reference host treats an interactive terminal outside any runtime worktree, with no provider
run in progress, as that evidence. Nothing here proves operating-system identity; the posture is
advisory and is recorded as such on every event.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

HOST_TTY = "host-tty"
UNAUTHENTICATED = "none"
AGENT_RUN_VARIABLE = "INVARIANT_AGENT_RUN"
RUNTIME_WORKTREE_PARTS = (".invariant", "runtime", "worktrees")


def inside_runtime_worktree(path: Path | None = None) -> bool:
    parts = (path or Path.cwd()).resolve().parts
    return any(
        parts[index : index + 3] == RUNTIME_WORKTREE_PARTS
        for index in range(len(parts) - 2)
    )


def authenticate_user(path: Path | None = None) -> str:
    """Return the authentication method the current process can claim for a user principal."""

    if os.environ.get(AGENT_RUN_VARIABLE):
        return UNAUTHENTICATED
    if inside_runtime_worktree(path):
        return UNAUTHENTICATED
    try:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        interactive = False
    return HOST_TTY if interactive else UNAUTHENTICATED


def refusal_lines() -> list[str]:
    return [
        "STATUS: direct user authority requires the interactive host",
        "NEXT: run this from a terminal outside .invariant/runtime/worktrees, not from a provider run",
    ]
