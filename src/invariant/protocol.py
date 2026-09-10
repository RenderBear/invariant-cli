from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Mapping

from invariant.errors import UsageError


class TaskStage(StrEnum):
    BRIEFED = "briefed"
    BRIEFING = "briefing"
    AWAITING_BRANCH = "awaiting-branch"
    IMPLEMENTING = "implementing"
    IMPLEMENTING_UNBORN = "implementing-unborn"
    AWAITING_REVIEW = "awaiting-review"
    AWAITING_LANDING = "awaiting-landing"
    CLEANUP_REQUIRED = "cleanup-required"
    COMPLETED = "completed"

    @classmethod
    def parse(cls, value: object, *, default: "TaskStage | None" = None) -> "TaskStage":
        if (value is None or value == "") and default is not None:
            return default
        try:
            return cls(str(value))
        except ValueError:
            raise UsageError(f"unknown task stage '{value}'") from None


class CommandOutcome(StrEnum):
    COMPLETED = "completed"
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    FAILED = "failed"


class Reach(StrEnum):
    LOCAL = "local"
    BOUNDED = "bounded"
    OPEN = "open"
    GATED = "gated"

    @property
    def needs_explicit_authority(self) -> bool:
        return self in {Reach.OPEN, Reach.GATED}


class BoundaryKind(StrEnum):
    UNRESOLVED = "unresolved"
    NO_RECORD = "no-record"
    RECORDED = "recorded"
    AUDIT = "audit"


@dataclass(frozen=True)
class BoundaryDisposition:
    kind: BoundaryKind
    audit_id: str | None = None

    @classmethod
    def parse(
        cls, value: object, *, allow_unresolved: bool = True
    ) -> "BoundaryDisposition":
        if not isinstance(value, str):
            raise UsageError("boundary disposition must be text")
        if value == BoundaryKind.UNRESOLVED:
            if not allow_unresolved:
                raise UsageError("boundary disposition cannot remain unresolved")
            return cls(BoundaryKind.UNRESOLVED)
        if value == BoundaryKind.NO_RECORD:
            return cls(BoundaryKind.NO_RECORD)
        if value == BoundaryKind.RECORDED:
            return cls(BoundaryKind.RECORDED)
        if value.startswith("audit:"):
            identifier = value.removeprefix("audit:")
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
                return cls(BoundaryKind.AUDIT, identifier)
        raise UsageError(
            "boundary disposition must be unresolved, no-record, recorded, or audit:<id>"
        )

    @property
    def value(self) -> str:
        return f"audit:{self.audit_id}" if self.kind == BoundaryKind.AUDIT else self.kind.value

    @property
    def resolved(self) -> bool:
        return self.kind != BoundaryKind.UNRESOLVED

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Evidence:
    """One attributable observation with a stable identifier and open payload."""

    identifier: str
    kind: str
    payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Evidence":
        identifier = value.get("evidence_id")
        kind = value.get("kind")
        if not isinstance(identifier, str) or not identifier:
            raise UsageError("evidence requires a stable evidence_id")
        if not isinstance(kind, str) or not kind:
            raise UsageError("evidence requires a kind")
        return cls(
            identifier=identifier,
            kind=kind,
            payload={
                name: item
                for name, item in value.items()
                if name not in {"evidence_id", "kind"}
            },
        )

    def as_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.identifier, "kind": self.kind, **self.payload}
