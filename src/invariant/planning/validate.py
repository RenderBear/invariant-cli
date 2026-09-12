from __future__ import annotations

from typing import Sequence

from invariant.errors import InvariantError
from invariant.governance.selection import paths_overlap
from invariant.planning.model import Unit


def _claim_overlap(left: str, right: str) -> bool:
    if left.startswith("repo:") and right.startswith("repo:"):
        return paths_overlap(left, right)
    return left == right and left.startswith(("interface:", "contract:"))


def _reaches(unit: Unit, locators: Sequence[str]) -> bool:
    return any(_claim_overlap(claim, locator) for claim in unit.claims for locator in locators)


def validate(
    units: Sequence[Unit], serialize_on: Sequence[str] = ()
) -> tuple[tuple[str, str], ...]:
    if not 1 <= len(units) <= 32:
        raise InvariantError("Invariant: recommendation requires 1 to 32 units", code="invalid_recommendation")
    by_id = {unit.identifier: unit for unit in units}
    if len(by_id) != len(units):
        raise InvariantError("Invariant: recommendation has duplicate unit ids", code="invalid_recommendation")
    for unit in units:
        missing = set(unit.depends_on) - set(by_id)
        if missing or unit.identifier in unit.depends_on:
            raise InvariantError("Invariant: recommendation has an invalid dependency", code="invalid_recommendation")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise InvariantError("Invariant: recommendation dependency cycle", code="invalid_recommendation")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in by_id[identifier].depends_on:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in by_id:
        visit(identifier)

    providers: dict[str, str] = {}
    for unit in units:
        for contract in unit.provides:
            if contract in providers:
                raise InvariantError(f"Invariant: contract '{contract}' has multiple providers", code="contract_order_violation")
            providers[contract] = unit.identifier
    for unit in units:
        ancestors: set[str] = set()
        pending = list(unit.depends_on)
        while pending:
            value = pending.pop()
            if value not in ancestors:
                ancestors.add(value)
                pending.extend(by_id[value].depends_on)
        for contract in unit.relies_on:
            provider = providers.get(contract)
            if provider and provider not in ancestors:
                raise InvariantError(
                    f"Invariant: consumer '{unit.identifier}' does not depend on provider '{provider}'",
                    code="contract_order_violation",
                )

    conflicts: set[tuple[str, str]] = set()
    for index, left in enumerate(units):
        for right in units[index + 1 :]:
            if any(_claim_overlap(a, b) for a in left.claims for b in right.claims):
                if right.identifier not in left.depends_on and left.identifier not in right.depends_on:
                    raise InvariantError(
                        f"Invariant: units '{left.identifier}' and '{right.identifier}' overlap without ordering",
                        code="overlapping_claims",
                    )
                conflicts.add(tuple(sorted((left.identifier, right.identifier))))
            elif serialize_on and _reaches(left, serialize_on) and _reaches(right, serialize_on):
                # A serialize directive: both units reach the serialized set, so they may not be live together.
                conflicts.add(tuple(sorted((left.identifier, right.identifier))))
    return tuple(sorted(conflicts))
