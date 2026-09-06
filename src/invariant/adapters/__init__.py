from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from invariant.adapters.base import HOOK_PHASES, HookContext, HookRequest, TaskAdapter
from invariant.adapters.intent_brief.adapter import IntentBriefAdapter
from invariant.errors import InvariantError


_REGISTRY: dict[str, TaskAdapter] = {"intent_brief": IntentBriefAdapter()}


def validate(ids: tuple[str, ...]) -> None:
    missing = [identifier for identifier in ids if identifier not in _REGISTRY]
    if missing:
        raise InvariantError(
            f"Invariant: configured adapter '{missing[0]}' is not installed",
            code="missing_adapter",
        )


def digest(ids: tuple[str, ...]) -> str:
    value = sha256()
    root = Path(__file__).resolve().parent
    for identifier in sorted(ids):
        adapter_root = root / identifier
        for path in sorted(adapter_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                value.update(path.relative_to(root).as_posix().encode())
                value.update(b"\0")
                value.update(path.read_bytes())
                value.update(b"\0")
    return value.hexdigest()


def enabled(receipt: Mapping[str, object]) -> tuple[str, ...]:
    value = receipt.get("adapters", [])
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def states(receipt: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    value = receipt.get("adapter_state")
    if not isinstance(value, dict):
        return {}
    return {
        str(name): dict(state)
        for name, state in value.items()
        if isinstance(name, str) and isinstance(state, dict)
    }


def pending(receipt: Mapping[str, object]) -> list[dict[str, Any]]:
    value = receipt.get("hook_requests", [])
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def action_descriptor(request: Mapping[str, object]) -> dict[str, Any]:
    """Return the expanded public form of a persisted action."""

    raw_context = request.get("context")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    evidence = context.pop("evidence", None)
    if isinstance(evidence, list):
        context["evidence_ids"] = [
            str(item.get("evidence_id"))
            for item in evidence
            if isinstance(item, dict) and item.get("evidence_id")
        ]
    if "brief" in context:
        context.pop("brief", None)
        context["brief_artifact"] = "intent-brief"
    kind = str(request.get("kind") or "action")
    return {
        "id": str(request.get("id") or ""),
        "adapter": str(request.get("adapter") or ""),
        "phase": str(request.get("phase") or ""),
        "kind": kind,
        "prompt": str(request.get("prompt") or ""),
        "schema_id": str(
            request.get("schema_id") or f"invariant://schemas/actions/{kind}/v1"
        ),
        "blocking": bool(request.get("blocking", True)),
        "context": context,
    }


def action_reference(request: Mapping[str, object]) -> dict[str, Any]:
    """Return the small lifecycle reference used before explicit expansion."""

    kind = str(request.get("kind") or "action")
    return {
        "id": str(request.get("id") or ""),
        "adapter": str(request.get("adapter") or ""),
        "phase": str(request.get("phase") or ""),
        "kind": kind,
        "schema_id": str(
            request.get("schema_id") or f"invariant://schemas/actions/{kind}/v1"
        ),
        "blocking": bool(request.get("blocking", True)),
    }


def action_descriptors(receipt: Mapping[str, object]) -> list[dict[str, Any]]:
    return [action_reference(item) for item in pending(receipt)]


def run_hook(
    task_root: Path,
    receipt: dict[str, object],
    phase: str,
    inputs: Mapping[str, str | None] | None = None,
    *,
    candidate_tree: str | None = None,
    evidence: tuple[dict[str, Any], ...] = (),
    retained_discoveries: tuple[str, ...] = (),
) -> list[HookRequest]:
    """Run all adapters for a lifecycle phase and collect every request.

    Requests are data, not exceptions or lifecycle stages.  The lifecycle may
    choose whether blocking requests prevent its next transition.
    """

    identifiers = enabled(receipt)
    validate(identifiers)
    if phase not in HOOK_PHASES:
        raise InvariantError(f"Invariant: unknown lifecycle hook phase '{phase}'")
    current = states(receipt)
    requests: list[HookRequest] = []
    previous_artifacts = receipt.get("hook_artifacts", [])
    artifacts: dict[tuple[str, str], dict[str, Any]] = {
        (str(item.get("adapter") or ""), str(item.get("id") or "")): dict(item)
        for item in previous_artifacts
        if isinstance(item, dict)
    } if isinstance(previous_artifacts, list) else {}
    context = HookContext(
        task_root=task_root,
        task=str(receipt.get("task") or ""),
        phase=phase,
        goal=str(receipt.get("goal") or ""),
        goal_digest=str(receipt.get("goal_digest") or ""),
        candidate_tree=candidate_tree,
        evidence=evidence,
        retained_discoveries=retained_discoveries,
    )
    for identifier in identifiers:
        result = _REGISTRY[identifier].handle(
            context,
            current.get(identifier),
            (inputs or {}).get(identifier),
        )
        current[identifier] = result.state
        for request in result.requests:
            if request.adapter != identifier or request.phase != phase:
                raise InvariantError(
                    f"Invariant: adapter '{identifier}' returned a request for the wrong hook"
                )
            requests.append(request)
        for artifact in result.artifacts:
            value = {**artifact, "adapter": identifier, "phase": phase}
            artifacts[(identifier, str(value.get("id") or value.get("kind") or ""))] = value
    request_ids = [request.id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise InvariantError("Invariant: lifecycle hook request ids must be unique")
    receipt["adapter_state"] = current
    receipt["hook_requests"] = [request.as_dict() for request in requests]
    receipt["hook_artifacts"] = list(artifacts.values())
    return requests


def context(task_root: Path, receipt: dict[str, object]) -> list[str]:
    output: list[str] = []
    validate(enabled(receipt))
    current = states(receipt)
    for identifier in enabled(receipt):
        lines = _REGISTRY[identifier].context(task_root, current.get(identifier, {}))
        if lines:
            if output:
                output.append("")
            output.extend(lines)
    return output


def guidance(receipt: dict[str, object], phase: str) -> list[str]:
    output: list[str] = []
    validate(enabled(receipt))
    for identifier in enabled(receipt):
        content = _REGISTRY[identifier].guidance(phase)
        if output:
            output.append("")
        output.extend(content.splitlines())
    return output


def schemas(identifier: str = "intent_brief") -> dict[str, Any]:
    validate((identifier,))
    return _REGISTRY[identifier].schemas()


def examples(identifier: str = "intent_brief") -> dict[str, Any]:
    validate((identifier,))
    return _REGISTRY[identifier].examples()
