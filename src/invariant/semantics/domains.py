from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Iterator

from invariant.errors import UsageError


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"{label} must be non-empty text")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    result = _text(value, label)
    if not _IDENTIFIER.fullmatch(result):
        raise UsageError(f"{label} is invalid")
    return result


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise UsageError(f"{label} must be a list of non-empty strings")
    return tuple(sorted(set(item.strip() for item in value)))


@dataclass(frozen=True)
class Domain:
    """A stable responsibility used to retrieve accepted semantic context.

    Responsibility remains prose.  The typed fields describe only identity,
    authority, hierarchy, and links to accepted architecture and contracts.
    A domain does not infer ownership from a directory and is not a lock.
    """

    identifier: str
    responsibility: str
    authority: str
    parent: str | None = None
    architecture: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()

    @property
    def reference(self) -> str:
        return f"domain:{self.identifier}"

    @classmethod
    def parse(cls, value: Any, index: int = 0) -> "Domain":
        label = f"domains[{index}]"
        if not isinstance(value, dict):
            raise UsageError(f"{label} must be a mapping")
        allowed = {
            "id",
            "responsibility",
            "authority",
            "parent",
            "architecture",
            "contracts",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise UsageError(f"{label} has unknown field '{unknown[0]}'")
        parent_raw = value.get("parent")
        parent = (
            _identifier(parent_raw, f"{label}.parent")
            if parent_raw is not None
            else None
        )
        contracts = _strings(value.get("contracts"), f"{label}.contracts")
        for contract in contracts:
            _identifier(contract, f"{label}.contracts")
        return cls(
            identifier=_identifier(value.get("id"), f"{label}.id"),
            responsibility=_text(
                value.get("responsibility"), f"{label}.responsibility"
            ),
            authority=_text(value.get("authority"), f"{label}.authority"),
            parent=parent,
            architecture=_strings(
                value.get("architecture"), f"{label}.architecture"
            ),
            contracts=contracts,
        )

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.identifier,
            "responsibility": self.responsibility,
            "authority": self.authority,
        }
        if self.parent:
            value["parent"] = self.parent
        if self.architecture:
            value["architecture"] = list(self.architecture)
        if self.contracts:
            value["contracts"] = list(self.contracts)
        return value


@dataclass(frozen=True)
class DomainIndex:
    """An immutable, validated domain hierarchy and retrieval index."""

    entries: tuple[Domain, ...] = ()

    @classmethod
    def parse_document(cls, raw: Any) -> "DomainIndex":
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise UsageError("domain index must be a version-1 mapping")
        unknown = sorted(set(raw) - {"version", "domains"})
        if unknown:
            raise UsageError(f"domain index has unknown field '{unknown[0]}'")
        values = raw.get("domains")
        if not isinstance(values, list) or not values:
            raise UsageError("domain index contains no domains; remove it")
        entries = tuple(Domain.parse(value, index) for index, value in enumerate(values))
        identifiers = [entry.identifier for entry in entries]
        duplicate = next(
            (identifier for identifier in identifiers if identifiers.count(identifier) > 1),
            None,
        )
        if duplicate:
            raise UsageError(f"duplicate domain '{duplicate}'")
        known = set(identifiers)
        for entry in entries:
            if entry.parent and entry.parent not in known:
                raise UsageError(
                    f"domain '{entry.identifier}' references missing parent '{entry.parent}'"
                )
        index = cls(tuple(sorted(entries, key=lambda entry: entry.identifier)))
        index._validate_acyclic()
        return index

    def __iter__(self) -> Iterator[Domain]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def identifiers(self) -> tuple[str, ...]:
        return tuple(entry.identifier for entry in self.entries)

    def get(self, identifier: str) -> Domain | None:
        return next(
            (entry for entry in self.entries if entry.identifier == identifier), None
        )

    def require(self, identifier: str) -> Domain:
        result = self.get(identifier)
        if result is None:
            raise UsageError(f"unknown semantic domain '{identifier}'")
        return result

    def expand(self, selected: Iterable[str]) -> tuple[Domain, ...]:
        """Return selected domains plus ancestors, in stable identifier order."""

        expanded: set[str] = set()
        pending = list(dict.fromkeys(selected))
        while pending:
            identifier = pending.pop()
            entry = self.require(identifier)
            if entry.identifier in expanded:
                continue
            expanded.add(entry.identifier)
            if entry.parent:
                pending.append(entry.parent)
        return tuple(entry for entry in self.entries if entry.identifier in expanded)

    def as_document(self) -> dict[str, Any]:
        return {"version": 1, "domains": [entry.as_dict() for entry in self.entries]}

    def _validate_acyclic(self) -> None:
        parents = {
            entry.identifier: entry.parent
            for entry in self.entries
            if entry.parent is not None
        }
        for identifier in parents:
            path: list[str] = []
            current = identifier
            while current in parents:
                if current in path:
                    cycle = path[path.index(current) :] + [current]
                    raise UsageError(
                        "domain parent graph contains a cycle: " + " -> ".join(cycle)
                    )
                path.append(current)
                current = str(parents[current])
