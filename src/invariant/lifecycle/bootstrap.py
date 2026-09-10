from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from invariant.errors import InvariantError
from invariant.mechanics import config, git


ESTABLISH_COMMAND = "invariant establish"


@dataclass(frozen=True)
class BootstrapSettings:
    authority: str = "agent"
    execution: str = "auto"
    integration_branch: str = "auto"
    push_remote: str = "off"
    intent_brief: bool = False


def initialize(
    repo: Path, settings: BootstrapSettings, *, overwrite: bool = False
) -> list[str]:
    git.require_capabilities(repo)
    nested = git.tracked_nested_invariant_paths(repo)
    if nested:
        raise InvariantError(
            "Invariant: this Git repository contains nested Invariant state",
            code="nested_invariant",
            lines=[
                f"NESTED: {path}" for path in nested
            ] + ["NEXT: keep one .invariant directory at the Git repository root"],
        )
    config.initialize(
        repo,
        authority=settings.authority,
        execution=settings.execution,
        integration_branch=settings.integration_branch,
        push_remote=settings.push_remote,
        intent_brief=settings.intent_brief,
        overwrite=overwrite,
    )
    resolved = config.resolve(repo)
    return [
        "INITIALIZED: repository",
        f"CONFIG: {config.CONFIG_PATH.as_posix()}",
        f"AUTHORITY: {settings.authority}",
        f"EXECUTION: {settings.execution}",
        f"INTEGRATION-BRANCH: {resolved.integration_branch}",
        f"INTEGRATION-BRANCH-SETTING: {settings.integration_branch}",
        f"PUSH-REMOTE: {settings.push_remote}",
        f"INTENT-BRIEF-ADAPTER: {'on' if settings.intent_brief else 'off'}",
        f"PROMPT: {ESTABLISH_COMMAND}",
    ]
