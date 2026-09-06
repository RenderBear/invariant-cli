from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from invariant.errors import InvariantError
from invariant.mechanics import config, git
from invariant.semantics import guidance


START = "<!-- invariant:workflow:start -->"
END = "<!-- invariant:workflow:end -->"
GOVERNANCE_PROMPT = "Run a governance pass for the repository with Invariant."


@dataclass(frozen=True)
class BootstrapSettings:
    coding_agents: tuple[str, ...] = ("codex", "claude")
    authority: str = "agent"
    execution: str = "auto"
    integration_branch: str = "auto"
    push_remote: str = "off"
    task_acceptance: bool = False


def _managed(text: str, body: str, path: Path) -> str:
    count_start = text.count(START)
    count_end = text.count(END)
    if count_start or count_end:
        if count_start != 1 or count_end != 1 or text.index(START) > text.index(END):
            raise InvariantError(
                f"Invariant: {path.name} contains an ambiguous managed workflow block",
                code="ambiguous_agent_instructions",
            )
        before, remainder = text.split(START, 1)
        _, after = remainder.split(END, 1)
        return f"{before}{START}\n{body.rstrip()}\n{END}{after}"
    if "## Invariant lifecycle" in text:
        raise InvariantError(
            f"Invariant: {path.name} already contains an unmanaged Invariant lifecycle section",
            code="ambiguous_agent_instructions",
        )
    prefix = text.rstrip()
    block = f"{START}\n{body.rstrip()}\n{END}\n"
    return f"{prefix}\n\n{block}" if prefix else block


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise InvariantError(
            f"Invariant: {path.name} is not a regular file", code="invalid_agent_instructions"
        )
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    descriptor, pending_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    pending = Path(pending_name)
    try:
        if path.exists():
            os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        pending.replace(path)
    finally:
        if pending.exists():
            pending.unlink()


def _instruction_updates(repo: Path, coding_agents: tuple[str, ...]) -> dict[Path, str]:
    selected = set(coding_agents)
    workflow = guidance.agent_workflow()
    updates: dict[Path, str] = {}
    agents = repo / "AGENTS.md"
    claude = repo / "CLAUDE.md"

    if "codex" in selected:
        current = _read(agents)
        updated = _managed(current, workflow, agents)
        if updated != current:
            updates[agents] = updated

    if "claude" in selected:
        current = _read(claude)
        if "codex" in selected:
            if (
                "@AGENTS.md" in current
                and "## Invariant lifecycle" not in current
                and START not in current
                and END not in current
            ):
                updated = current
            else:
                updated = _managed(current, "@AGENTS.md", claude)
        else:
            updated = _managed(current, workflow, claude)
        if updated != current:
            updates[claude] = updated

    return updates


def initialize(repo: Path, settings: BootstrapSettings) -> list[str]:
    git.require_capabilities(repo)
    updates = _instruction_updates(repo, settings.coding_agents)
    config.initialize(
        repo,
        coding_agents=settings.coding_agents,
        authority=settings.authority,
        execution=settings.execution,
        integration_branch=settings.integration_branch,
        push_remote=settings.push_remote,
        task_acceptance=settings.task_acceptance,
    )
    for path, text in updates.items():
        _write(path, text)
    resolved = config.resolve(repo)

    instruction_lines = [
        f"INSTRUCTIONS: configured {path.relative_to(repo).as_posix()}" for path in updates
    ]
    if "claude" in settings.coding_agents and "codex" in settings.coding_agents and not any(
        path.name == "CLAUDE.md" for path in updates
    ):
        instruction_lines.append("INSTRUCTIONS: CLAUDE.md already imports AGENTS.md")
    return [
        "INITIALIZED: repository",
        f"CONFIG: {config.CONFIG_PATH.as_posix()}",
        f"CODING-AGENTS: {', '.join(settings.coding_agents)}",
        f"AUTHORITY: {settings.authority}",
        f"EXECUTION: {settings.execution}",
        f"INTEGRATION-BRANCH: {resolved.integration_branch}",
        f"INTEGRATION-BRANCH-SETTING: {settings.integration_branch}",
        f"PUSH-REMOTE: {settings.push_remote}",
        f"TASK-ACCEPTANCE-ADAPTER: {'on' if settings.task_acceptance else 'off'}",
        *instruction_lines,
        f"PROMPT: {GOVERNANCE_PROMPT}",
    ]
