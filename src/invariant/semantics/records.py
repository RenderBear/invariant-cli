from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from invariant.errors import UsageError


def _strings(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise UsageError(f"{label} must be a list of non-empty strings")
    return sorted(set(value))


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"{label} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class SemanticRecord:
    """A small mechanical envelope around canonical prose.

    The CLI understands only the coordinates needed to retrieve, invalidate,
    verify, and supersede meaning.  The referenced Markdown remains the
    semantic body; ``facets`` and relation names deliberately stay open.
    """

    identifier: str
    document: str
    authority: str
    status: str = "active"
    applies_to: list[str] = field(default_factory=list)
    revisit_on: list[str] = field(default_factory=list)
    verifies: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    relations: dict[str, list[str]] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "document": self.document,
            "authority": self.authority,
            "status": self.status,
            "applies_to": list(self.applies_to),
            "revisit_on": list(self.revisit_on),
            "verifies": list(self.verifies),
            "supersedes": list(self.supersedes),
            "relations": {name: list(targets) for name, targets in self.relations.items()},
            "facets": dict(self.facets),
        }

    @classmethod
    def parse(cls, value: Any, index: int = 0) -> "SemanticRecord":
        label = f"semantic records[{index}]"
        if not isinstance(value, dict):
            raise UsageError(f"{label} must be a mapping")
        allowed = {
            "id",
            "document",
            "authority",
            "status",
            "applies_to",
            "revisit_on",
            "verifies",
            "supersedes",
            "relations",
            "facets",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise UsageError(f"{label} has unknown field '{unknown[0]}'")
        identifier = _text(value.get("id"), f"{label}.id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
            raise UsageError(f"{label}.id is invalid")
        status = value.get("status", "active")
        if status not in {"active", "superseded"}:
            raise UsageError(f"{label}.status must be active or superseded")
        relations_raw = value.get("relations", {})
        if not isinstance(relations_raw, dict) or any(
            not isinstance(name, str)
            or not name.strip()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
            for name in relations_raw
        ):
            raise UsageError(f"{label}.relations must be a mapping with stable names")
        relations = {
            str(name): _strings(targets, f"{label}.relations.{name}")
            for name, targets in relations_raw.items()
        }
        facets = value.get("facets", {})
        if not isinstance(facets, dict) or any(
            not isinstance(name, str) or not name.strip() for name in facets
        ):
            raise UsageError(f"{label}.facets must be a mapping")
        return cls(
            identifier=identifier,
            document=_text(value.get("document"), f"{label}.document"),
            authority=_text(value.get("authority"), f"{label}.authority"),
            status=str(status),
            applies_to=_strings(value.get("applies_to"), f"{label}.applies_to"),
            revisit_on=_strings(value.get("revisit_on"), f"{label}.revisit_on"),
            verifies=_strings(value.get("verifies"), f"{label}.verifies"),
            supersedes=_strings(value.get("supersedes"), f"{label}.supersedes"),
            relations=relations,
            facets=dict(facets),
        )


def parse_document(raw: Any) -> list[SemanticRecord]:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise UsageError("semantic record index must be a version-1 mapping")
    unknown = sorted(set(raw) - {"version", "records"})
    if unknown:
        raise UsageError(f"semantic record index has unknown field '{unknown[0]}'")
    values = raw.get("records")
    if not isinstance(values, list) or not values:
        raise UsageError("semantic record index contains no records; remove it")
    records = [SemanticRecord.parse(value, index) for index, value in enumerate(values)]
    identifiers = [record.identifier for record in records]
    if len(identifiers) != len(set(identifiers)):
        duplicate = next(item for item in identifiers if identifiers.count(item) > 1)
        raise UsageError(f"duplicate semantic record '{duplicate}'")
    return records
