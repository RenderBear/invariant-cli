from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from invariant.errors import InvariantError
from invariant.protocol import PROTOCOL_VERSION, digest, require_id


@dataclass(frozen=True)
class Unit:
    identifier: str
    objective: str
    claims: tuple[str, ...]
    provides: tuple[str, ...] = ()
    relies_on: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: object, index: int) -> "Unit":
        label = f"units[{index}]"
        if not isinstance(value, dict):
            raise InvariantError(f"Invariant: {label} must be a mapping", code="invalid_recommendation")
        allowed = {"id", "objective", "claims", "provides", "relies_on", "depends_on", "checks"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise InvariantError(f"Invariant: {label} has unknown field '{unknown[0]}'", code="invalid_recommendation")
        identifier = require_id(value.get("id"), f"{label}.id")
        objective = value.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise InvariantError(f"Invariant: {label}.objective must be non-empty", code="invalid_recommendation")

        def strings(name: str, required: bool = False) -> tuple[str, ...]:
            raw = value.get(name, [])
            if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
                raise InvariantError(f"Invariant: {label}.{name} must be a string list", code="invalid_recommendation")
            result = tuple(dict.fromkeys(item.strip() for item in raw))
            if required and not result:
                raise InvariantError(f"Invariant: {label}.{name} cannot be empty", code="unbounded_unit")
            return result

        claims = strings("claims", True)
        for claim in claims:
            kind, separator, coordinate = claim.partition(":")
            if not separator or kind not in {"repo", "interface", "domain", "contract"}:
                raise InvariantError(
                    f"Invariant: {label}.claims contains untyped coordinate '{claim}'",
                    code="invalid_recommendation",
                )
            if kind == "repo":
                path = Path(coordinate)
                if not coordinate or path.is_absolute() or ".." in path.parts:
                    raise InvariantError(
                        f"Invariant: {label}.claims contains invalid repository path '{claim}'",
                        code="invalid_recommendation",
                    )
            else:
                require_id(coordinate, f"{label}.claims coordinate")
        provides = strings("provides")
        relies_on = strings("relies_on")
        for contract in (*provides, *relies_on):
            prefix, separator, identifier = contract.partition(":")
            if prefix != "contract" or not separator:
                raise InvariantError(
                    f"Invariant: {label} contract edges must use contract:<id>",
                    code="invalid_recommendation",
                )
            require_id(identifier, f"{label} contract")
        checks = strings("checks")
        for check in checks:
            kind, separator, path_value = check.partition(":")
            path = Path(path_value)
            if (
                kind not in {"command", "test"}
                or not separator
                or not path_value
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise InvariantError(
                    f"Invariant: {label}.checks contains invalid verifier '{check}'",
                    code="invalid_recommendation",
                )

        return cls(
            identifier,
            objective.strip(),
            claims,
            provides,
            relies_on,
            strings("depends_on"),
            checks,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "objective": self.objective,
            "claims": list(self.claims),
            "provides": list(self.provides),
            "relies_on": list(self.relies_on),
            "depends_on": list(self.depends_on),
            "checks": list(self.checks),
        }


@dataclass(frozen=True)
class Recommendation:
    identifier: str
    change: str
    base: str
    intent: str
    disposition: str
    units: tuple[Unit, ...]
    conflicts: tuple[tuple[str, str], ...]
    maximum_parallelism: int
    recommended_frontier: tuple[str, ...]
    governance: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        identifier: str,
        change: str,
        base: str,
        intent: str,
        units: Sequence[Unit],
        conflicts: Sequence[tuple[str, str]],
        maximum_parallelism: int,
        recommended_frontier: Sequence[str],
        governance: Sequence[str],
    ) -> "Recommendation":
        body = {
            "version": PROTOCOL_VERSION,
            "id": identifier,
            "change": change,
            "base": base,
            "intent": intent,
            "disposition": "parallel" if len(units) > 1 else "single",
            "units": [unit.as_dict() for unit in units],
            "conflicts": [list(pair) for pair in conflicts],
            "maximum_parallelism": maximum_parallelism,
            "recommended_frontier": list(recommended_frontier),
            "governance": list(governance),
        }
        return cls(
            identifier, change, base, intent, body["disposition"], tuple(units),
            tuple(conflicts), maximum_parallelism, tuple(recommended_frontier),
            tuple(governance), digest(body),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": PROTOCOL_VERSION,
            "id": self.identifier,
            "change": self.change,
            "base": self.base,
            "intent": self.intent,
            "disposition": self.disposition,
            "units": [unit.as_dict() for unit in self.units],
            "conflicts": [list(pair) for pair in self.conflicts],
            "maximum_parallelism": self.maximum_parallelism,
            "recommended_frontier": list(self.recommended_frontier),
            "governance": list(self.governance),
            "digest": self.digest,
        }
