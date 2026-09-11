from __future__ import annotations

from pathlib import Path
from typing import Any

from invariant.errors import InvariantError
from invariant.harness import preferences
from invariant.harness.providers import AgentProvider, connection_status
from invariant.semantics import sources


def resolve_provider(repo: Path, requested: AgentProvider | None = None) -> AgentProvider:
    configured = preferences.repo_harness(repo)
    candidates = [requested] if requested is not None else preferences.harness_candidates(repo)
    for provider in candidates:
        state = connection_status(provider)
        if state.installed and state.authenticated:
            return provider
    if requested is not None or configured != "auto":
        provider = requested or AgentProvider(configured)
        raise InvariantError(
            f"Invariant: {provider.value} is not connected; run 'invariant connect {provider.value}'",
            code="agent_not_connected",
        )
    raise InvariantError(
        "Invariant: no coding agent is connected; run 'invariant connect codex' or "
        "'invariant connect claude'",
        code="agent_not_connected",
    )


def schema(mode: str) -> dict[str, Any]:
    properties: dict[str, Any] = {"message": {"type": "string", "minLength": 1}}
    required = ["message"]
    if mode == "change":
        properties["action"] = {"type": "string", "enum": ["answer", "change"]}
        required.insert(0, "action")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def prompt(repo: Path, mode: str, message: str) -> str:
    if mode == "ask":
        instruction = (
            "Answer the user's repository question. This is a persistent conversation, so use "
            "relevant context from earlier turns."
        )
    else:
        instruction = (
            "Act as a read-only coordinator. Choose action=answer for questions, explanation, "
            "or exploration. Choose action=change only when the user asks to modify repository "
            "state. For a change, message must be a self-contained implementation request for "
            "Invariant's managed change lifecycle. For an answer, message is the answer."
        )
    grounding = sources.prompt_context(repo)
    suffix = f"\n\n{grounding}" if grounding else ""
    return (
        "You are working through an Invariant repository session. Inspect the repository when "
        "useful, but do not modify files, create commits, or change external state in this "
        "conversation. Return exactly one JSON object matching the supplied schema.\n\n"
        f"Session mode: {mode}\n{instruction}\n\nUser message:\n{message.strip()}\n{suffix}"
    )
