from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Mapping

from invariant.adapters.base import AdapterGate, TaskAdapter
from invariant.adapters.task_contract.adapter import (
    TaskContractAdapter,
    contract_schema,
    examples,
    review_schema,
)
from invariant.errors import InvariantError


_REGISTRY: dict[str, TaskAdapter] = {"task_contract": TaskContractAdapter()}


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


def states(receipt: Mapping[str, object]) -> dict[str, dict[str, object]]:
    value = receipt.get("adapter_state")
    if not isinstance(value, dict):
        return {}
    return {
        str(name): dict(state)
        for name, state in value.items()
        if isinstance(name, str) and isinstance(state, dict)
    }


def begin(
    task_root: Path,
    receipt: dict[str, object],
    inputs: Mapping[str, str | None],
) -> AdapterGate | None:
    identifiers = enabled(receipt)
    validate(identifiers)
    current = states(receipt)
    for identifier in identifiers:
        state, gate = _REGISTRY[identifier].begin(
            task_root,
            str(receipt.get("goal_digest") or ""),
            inputs.get(identifier),
            current.get(identifier),
        )
        if gate:
            receipt["adapter_state"] = current
            return gate
        if state is not None:
            current[identifier] = state
    receipt["adapter_state"] = current
    return None


def prepare_candidate(
    task_root: Path,
    receipt: dict[str, object],
    candidate_tree: str,
) -> list[dict[str, object]]:
    identifiers = enabled(receipt)
    validate(identifiers)
    current = states(receipt)
    missing = [identifier for identifier in identifiers if identifier not in current]
    if missing:
        raise InvariantError(
            f"Invariant: task has no captured state for adapter '{missing[0]}'",
            code="corrupt_receipt",
        )
    return [
        _REGISTRY[identifier].prepare_candidate(
            task_root,
            str(receipt.get("goal_digest") or ""),
            candidate_tree,
            current[identifier],
        )
        for identifier in identifiers
    ]


def review_candidate(
    task_root: Path,
    receipt: dict[str, object],
    candidate_tree: str,
    inputs: Mapping[str, str | None],
) -> AdapterGate | None:
    identifiers = enabled(receipt)
    validate(identifiers)
    current = states(receipt)
    missing = [identifier for identifier in identifiers if identifier not in current]
    if missing:
        raise InvariantError(
            f"Invariant: task has no captured state for adapter '{missing[0]}'",
            code="corrupt_receipt",
        )
    for identifier in identifiers:
        gate = _REGISTRY[identifier].review_candidate(
            task_root,
            str(receipt.get("goal_digest") or ""),
            candidate_tree,
            inputs.get(identifier),
            current[identifier],
        )
        if gate:
            return gate
    return None


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


def guidance(receipt: dict[str, object], stage: str) -> list[str]:
    output: list[str] = []
    validate(enabled(receipt))
    for identifier in enabled(receipt):
        text = _REGISTRY[identifier].guidance(stage)
        if output:
            output.append("")
        output.extend(text.splitlines())
    return output


def gate_for_stage(receipt: dict[str, object], stage: str) -> AdapterGate | None:
    for identifier in enabled(receipt):
        adapter = _REGISTRY[identifier]
        if stage == getattr(adapter, "begin_stage", ""):
            return AdapterGate(
                stage,
                f"Invariant: task needs input for the {identifier} adapter",
                "adapter_input_required",
            )
        if stage == getattr(adapter, "review_stage", ""):
            return AdapterGate(
                stage,
                f"Invariant: task needs candidate review from the {identifier} adapter",
                "adapter_review_required",
            )
    return None


def is_review_stage(receipt: dict[str, object], stage: str) -> bool:
    return any(
        stage == getattr(_REGISTRY[identifier], "review_stage", "")
        for identifier in enabled(receipt)
    )


def is_begin_stage(receipt: dict[str, object], stage: str) -> bool:
    return any(
        stage == getattr(_REGISTRY[identifier], "begin_stage", "")
        for identifier in enabled(receipt)
    )


def begin_stage(ids: tuple[str, ...]) -> str:
    validate(ids)
    if not ids:
        raise InvariantError("Invariant: no adapter is enabled", code="missing_adapter")
    return str(getattr(_REGISTRY[ids[0]], "begin_stage"))


def schemas() -> dict[str, object]:
    return {"contract": contract_schema(), "review": review_schema()}


def task_contract_examples() -> dict[str, object]:
    return examples()
