from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from invariant.errors import UsageError


LEVELS = ("inspection", "targeted", "broad")


def _load(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"Invariant: no such file '{source}'") from None
    except yaml.YAMLError as exc:
        raise UsageError(f"Invariant: invalid YAML in {source}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise UsageError(f"{label} must be a version-1 YAML mapping")
    return raw


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"{field_name} must be non-empty text")
    return value


def _valid_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value))


@dataclass(frozen=True)
class AcceptanceNode:
    id: str
    prose: str

    @classmethod
    def from_value(cls, value: Any, section: str, index: int) -> "AcceptanceNode":
        if not isinstance(value, dict):
            raise UsageError(f"task contract {section}[{index}] must be a mapping")
        unknown = sorted(set(value) - {"id", "prose"})
        if unknown:
            raise UsageError(
                f"task contract {section}[{index}] has unknown field '{unknown[0]}'"
            )
        identifier = value.get("id")
        if not isinstance(identifier, str) or not _valid_id(identifier):
            raise UsageError(f"task contract {section}[{index}] requires a valid id")
        return cls(
            identifier,
            _text(value.get("prose"), f"task contract {section}[{index}] prose"),
        )


@dataclass(frozen=True)
class TaskContract:
    source_goal_digest: str
    goal: str
    verification_level: str
    verification_rationale: str
    outcomes: list[AcceptanceNode] = field(default_factory=list)
    acceptance: list[AcceptanceNode] = field(default_factory=list)
    constraints: list[AcceptanceNode] = field(default_factory=list)

    @property
    def required(self) -> list[str]:
        selected = [node.id for node in (self.acceptance or self.outcomes)] or ["goal"]
        return [*selected, *[node.id for node in self.constraints]]

    @property
    def nodes(self) -> dict[str, list[str]]:
        return {
            "outcomes": [node.id for node in self.outcomes],
            "acceptance": [node.id for node in self.acceptance],
            "constraints": [node.id for node in self.constraints],
        }

    @classmethod
    def load(cls, path: str | Path) -> "TaskContract":
        raw = _load(path, "task contract")
        allowed = {"version", "adapter", "source_goal_digest", "requirements", "verification"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"task contract has unknown field '{unknown[0]}'")
        if raw.get("adapter") != "task_contract":
            raise UsageError("task contract requires adapter: task_contract")
        source_goal_digest = _text(
            raw.get("source_goal_digest"), "task contract source_goal_digest"
        )
        requirements = raw.get("requirements")
        if not isinstance(requirements, dict):
            raise UsageError("task contract requires a requirements mapping")
        requirement_unknown = sorted(
            set(requirements) - {"goal", "outcomes", "acceptance", "constraints"}
        )
        if requirement_unknown:
            raise UsageError(
                f"task contract requirements have unknown field '{requirement_unknown[0]}'"
            )

        def nodes(section: str) -> list[AcceptanceNode]:
            values = requirements.get(section, [])
            if not isinstance(values, list):
                raise UsageError(f"task contract {section} must be a list")
            return [
                AcceptanceNode.from_value(item, section, index)
                for index, item in enumerate(values)
            ]

        outcomes = nodes("outcomes")
        acceptance = nodes("acceptance")
        constraints = nodes("constraints")
        identifiers = [node.id for node in (*outcomes, *acceptance, *constraints)]
        if len(identifiers) != len(set(identifiers)):
            raise UsageError("task contract node ids must be unique")

        verification = raw.get("verification")
        if not isinstance(verification, dict):
            raise UsageError("task contract requires a verification mapping")
        verification_unknown = sorted(set(verification) - {"level", "rationale"})
        if verification_unknown:
            raise UsageError(
                f"task contract verification has unknown field '{verification_unknown[0]}'"
            )
        level = verification.get("level")
        if level not in LEVELS:
            raise UsageError(
                "task contract verification.level must be inspection, targeted, or broad"
            )
        return cls(
            source_goal_digest=source_goal_digest,
            goal=_text(requirements.get("goal"), "task contract goal"),
            verification_level=str(level),
            verification_rationale=_text(
                verification.get("rationale"), "task contract verification rationale"
            ),
            outcomes=outcomes,
            acceptance=acceptance,
            constraints=constraints,
        )


@dataclass(frozen=True)
class AcceptanceResult:
    reference: str
    disposition: str
    prose: str
    evidence: list[str]

    @classmethod
    def from_value(cls, value: Any, index: int) -> "AcceptanceResult":
        if not isinstance(value, dict):
            raise UsageError(f"task contract results[{index}] must be a mapping")
        unknown = sorted(set(value) - {"satisfies", "disposition", "prose", "evidence"})
        if unknown:
            raise UsageError(
                f"task contract results[{index}] has unknown field '{unknown[0]}'"
            )
        reference = _text(
            value.get("satisfies"), f"task contract results[{index}].satisfies"
        )
        disposition = value.get("disposition")
        if disposition not in {"satisfied", "not-satisfied", "unresolved"}:
            raise UsageError(
                f"task contract results[{index}].disposition must be satisfied, "
                "not-satisfied, or unresolved"
            )
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise UsageError(f"task contract results[{index}].evidence must be a string list")
        return cls(
            reference,
            str(disposition),
            _text(value.get("prose"), f"task contract results[{index}].prose"),
            sorted(set(evidence)),
        )


@dataclass(frozen=True)
class TaskContractReview:
    source_goal_digest: str
    candidate_tree: str
    results: list[AcceptanceResult]

    @classmethod
    def load(cls, path: str | Path) -> "TaskContractReview":
        raw = _load(path, "task contract review")
        allowed = {"version", "adapter", "source_goal_digest", "candidate_tree", "results"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"task contract review has unknown field '{unknown[0]}'")
        if raw.get("adapter") != "task_contract":
            raise UsageError("task contract review requires adapter: task_contract")
        results = raw.get("results")
        if not isinstance(results, list):
            raise UsageError("task contract review requires a results list")
        parsed = [AcceptanceResult.from_value(item, index) for index, item in enumerate(results)]
        references = [item.reference for item in parsed]
        if len(references) != len(set(references)):
            raise UsageError("task contract review cannot repeat a satisfies reference")
        return cls(
            _text(raw.get("source_goal_digest"), "task contract source_goal_digest"),
            _text(raw.get("candidate_tree"), "task contract candidate_tree"),
            parsed,
        )
