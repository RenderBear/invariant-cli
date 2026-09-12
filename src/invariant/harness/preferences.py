from __future__ import annotations

import os
import tempfile
from pathlib import Path

from invariant.errors import InvariantError
from invariant.harness.providers import AgentProvider
from invariant.mechanics import git


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def global_root() -> Path:
    configured = os.environ.get("INVARIANT_HOME")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "invariant"
    return Path.home() / ".config" / "invariant"


def _default_path() -> Path:
    return global_root() / "default-harness"


def default_harness() -> AgentProvider:
    configured = os.environ.get("INVARIANT_DEFAULT_HARNESS")
    path = _default_path()
    value = configured.strip() if configured is not None else ""
    if not value and path.is_file():
        value = path.read_text(encoding="utf-8").strip()
    if not value:
        return AgentProvider.CODEX
    try:
        return AgentProvider(value)
    except ValueError:
        source = "INVARIANT_DEFAULT_HARNESS" if configured is not None else str(path)
        raise InvariantError(
            f"Invariant: {source} must name codex or claude",
            code="invalid_default_harness",
        ) from None


def set_default_harness(provider: AgentProvider) -> None:
    overridden = os.environ.get("INVARIANT_DEFAULT_HARNESS")
    if overridden is not None:
        if overridden.strip() == provider.value:
            return
        raise InvariantError(
            "Invariant: unset INVARIANT_DEFAULT_HARNESS before changing the saved default",
            code="default_harness_overridden",
        )
    _write(_default_path(), provider.value)


HARNESS_CHOICES = ("auto", "codex", "claude")


def _harness_path(repo: Path) -> Path:
    return git.primary_worktree(repo) / ".invariant/runtime/harness"


def repo_harness(repo: Path) -> str:
    """The clone-local provider preference; `auto` follows the machine default."""

    path = _harness_path(repo)
    if not path.is_file():
        return "auto"
    value = path.read_text(encoding="utf-8").strip()
    if value not in HARNESS_CHOICES:
        raise InvariantError(
            f"Invariant: local harness preference must be auto, codex, or claude, not '{value}'",
            code="invalid_harness_preference",
        )
    return value


def set_repo_harness(repo: Path, value: str) -> None:
    if value not in HARNESS_CHOICES:
        raise InvariantError(
            "Invariant: harness must be auto, codex, or claude", code="invalid_harness_preference"
        )
    runtime = git.primary_worktree(repo) / ".invariant/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _write(runtime / "harness", value)


def harness_candidates(repo: Path) -> list[AgentProvider]:
    """Providers to try in order: the local preference alone, or the machine default then the rest."""

    preferred = repo_harness(repo)
    if preferred != "auto":
        return [AgentProvider(preferred)]
    default = default_harness()
    return [default, *[provider for provider in AgentProvider if provider != default]]


def effective_harness(repo: Path) -> AgentProvider:
    return harness_candidates(repo)[0]


def _mode_path(repo: Path) -> Path:
    return git.primary_worktree(repo) / ".invariant/runtime/session-mode"


def session_mode(repo: Path) -> str:
    path = _mode_path(repo)
    if not path.is_file():
        return "change"
    value = path.read_text(encoding="utf-8").strip()
    if value not in {"ask", "change"}:
        raise InvariantError(
            f"Invariant: local session mode must be ask or change, not '{value}'",
            code="invalid_session_mode",
        )
    return value


def set_session_mode(repo: Path, mode: str) -> None:
    if mode not in {"ask", "change"}:
        raise InvariantError(
            "Invariant: mode must be ask or change", code="invalid_session_mode"
        )
    runtime = git.primary_worktree(repo) / ".invariant/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _write(runtime / "session-mode", mode)
