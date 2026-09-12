from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from invariant.governance.records import Governance, Record
from invariant.protocol import CapabilityName, Scope, digest


def paths_overlap(left: str, right: str) -> bool:
    a = left.removeprefix("repo:").strip("/")
    b = right.removeprefix("repo:").strip("/")
    if a == "." or b == ".":
        return True
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


@dataclass(frozen=True)
class GovernanceSelection:
    records: tuple[Record, ...]
    reasons: Mapping[str, tuple[str, ...]]
    digest: str

    @classmethod
    def create(cls, records: Iterable[Record], reasons: Mapping[str, set[str]]) -> "GovernanceSelection":
        values = tuple(sorted(records, key=lambda item: (item.kind, item.identifier)))
        normalized = {key: tuple(sorted(value)) for key, value in sorted(reasons.items())}
        value_digest = digest(
            {"records": [record.reference for record in values], "reasons": normalized}
        )
        return cls(values, normalized, value_digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "records": [record.reference for record in self.records],
            "reasons": {key: list(value) for key, value in self.reasons.items()},
        }


def _intersects(record: Record, claims: set[str]) -> set[str]:
    matched: set[str] = set()
    coordinates = {
        f"repo:{record.path}",
        *record.strings("applies_to"),
        *record.strings("surfaces"),
        *record.strings("material"),
        *record.strings("scope"),
        *record.strings("interfaces"),
        *record.strings("architecture"),
    }
    document = record.data.get("document")
    if isinstance(document, str):
        coordinates.add(document)
    for coordinate in coordinates:
        comparable = coordinate
        if coordinate.startswith("architecture:"):
            architecture = coordinate.removeprefix("architecture:")
            path, separator, _ = architecture.rpartition("#")
            if separator:
                comparable = "repo:" + path.removeprefix("repo:")
        for claim in claims:
            if comparable == claim or (
                comparable.startswith("repo:")
                and claim.startswith("repo:")
                and paths_overlap(comparable, claim)
            ):
                matched.add(claim)
    if f"{record.kind}:{record.identifier}" in claims:
        matched.add(f"{record.kind}:{record.identifier}")
    return matched


def select(
    governance: Governance,
    scope: Scope,
    capability: CapabilityName | None = None,
) -> GovernanceSelection:
    claims = set(scope.claims)
    if capability:
        claims.add(f"capability:{capability.value}")
    selected: dict[tuple[str, str], Record] = {}
    reasons: dict[str, set[str]] = {}

    def include(record: Record, why: Iterable[str]) -> bool:
        key = (record.kind, record.identifier)
        reference = f"{record.kind}:{record.identifier}"
        before = key in selected
        selected[key] = record
        reasons.setdefault(reference, set()).update(why)
        return not before

    for record in governance.records:
        if record.kind == "semantic" and record.data.get("status") == "retired":
            continue
        matched = _intersects(record, claims)
        if matched:
            include(record, matched)

    changed = True
    while changed:
        changed = False
        for record in tuple(selected.values()):
            if record.kind == "domain":
                parent = record.data.get("parent")
                if parent:
                    target = governance.get("domain", str(parent))
                    if target:
                        changed |= include(target, {f"parent-of:domain:{record.identifier}"})
                for contract in record.strings("contracts"):
                    target = governance.get("contract", contract.removeprefix("contract:"))
                    if target:
                        changed |= include(target, {f"named-by:domain:{record.identifier}"})
            if record.kind == "semantic":
                for locator in record.strings("revisit_on"):
                    kind, _, identifier = locator.partition(":")
                    target = governance.get(kind, identifier)
                    if target:
                        changed |= include(target, {f"revisit-on:semantic:{record.identifier}"})
    return GovernanceSelection.create(selected.values(), reasons)
