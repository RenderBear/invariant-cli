from __future__ import annotations

from pathlib import Path
from typing import Any

from invariant.errors import InvariantError
from invariant.harness import preferences
from invariant.harness.providers import AgentProvider, connection_status


def establishment_intent(focus: str = "") -> str:
    """Expand the explicit establish control into bounded user-supplied intent."""

    emphasis = (
        f"\nGive particular attention to: {focus.strip()}\n"
        if focus.strip()
        else ""
    )
    return (
        "Establish or reconcile this repository's governance baseline. Inspect the current "
        "repository, its normative documentation, architecture, implementation boundaries, "
        "interfaces, and executable verification. If the accepted record set already captures "
        "the repository accurately and minimally, explain that no change is needed. Otherwise, "
        "propose a change that creates or updates only well-supported version-1 records beneath "
        ".invariant/records/ and one full audit beneath .invariant/audits/.\n\n"
        "Use semantic records for canonical interpretations, domain records for real ownership "
        "boundaries, contract records for actual provider-consumer interfaces, and constraint "
        "records for enforceable restrictions. Do not create one of every kind merely for "
        "coverage. Inspect protocol/protocol.md section 3, docs/SPEC.md, and the current record "
        "validator before authoring. Every repo path, document, architecture anchor, contract, "
        "interface, audit, command, and test locator must resolve in the exact candidate. Never "
        "invent a verifier or heading anchor. A constraint must have a real verifier or a closed "
        "directive. Prefer a small high-confidence baseline over speculative records.\n\n"
        "The audit must describe the inspected base without claiming authority: use a stable "
        "audit-<UTC timestamp> id and filename, an ISO-8601 created_at value, the current HEAD as "
        "ground, the current HEAD tree as tree, mode full, and evidence-backed findings. Use "
        "disposition adoptable only for findings projected into this same candidate. Governance "
        "acceptance belongs to the user; this request authorizes drafting the exact candidate, "
        "not accepting or landing it."
        + emphasis
    )


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
        properties["paths"] = {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        }
        required.insert(0, "action")
        required.append("paths")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def prompt(
    repo: Path,
    mode: str,
    message: str,
    *,
    decision_context: str = "",
) -> str:
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
    if decision_context:
        instruction = (
            "A durable-record proposal is awaiting the user's authority. Discuss and explain "
            "that proposal using the supplied decision context. Choose action=answer: discussion "
            "must not alter or accept the proposal. Only the user's :accept control action accepts "
            "the exact candidate."
        )
    return (
        "You are working through an Invariant repository session. Inspect the repository when "
        "useful, but do not modify files, create commits, or change external state in this "
        "conversation. Return exactly one JSON object matching the supplied schema.\n\n"
        f"Session mode: {mode}\n{instruction}\n"
        + (
            f"\nPending record decision:\n{decision_context.strip()}\n"
            if decision_context
            else ""
        )
        + (
            "\nWhen action=change, paths must contain the smallest repository-relative "
            "file or directory claims needed for the work. When action=answer, paths must "
            "be empty.\n"
            if mode == "change" and not decision_context
            else ""
        )
        + f"\nUser message:\n{message.strip()}\n"
    )
