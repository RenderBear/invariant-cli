"""Closed protocol-v1 values shared by every Invariant surface.

Open prose is deliberately absent from the capability vocabulary. The types in
this module are the mechanical boundary between supplied intent, semantic
resolution, and execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from invariant.errors import UsageError


PROTOCOL_VERSION = 1
FULL_DIGEST = re.compile(r"[0-9a-f]{64}")
OBJECT_ID = re.compile(r"[0-9a-f]{40,64}")
STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not FULL_DIGEST.fullmatch(value):
        raise UsageError(f"{label} must be a full SHA-256 digest")
    return value


def require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not STABLE_ID.fullmatch(value):
        raise UsageError(f"{label} must be a stable identifier")
    return value


class Outcome(StrEnum):
    COMPLETED = "completed"
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    DENIED = "denied"
    STALE = "stale"
    BLOCKED = "blocked"
    FAILED = "failed"


class ChangeStage(StrEnum):
    OPENED = "opened"
    RECOMMENDING = "recommending"
    READY = "ready"
    EXECUTING = "executing"
    CONVERGING = "converging"
    EVIDENCING = "evidencing"
    AWAITING_ACTION = "awaiting-action"
    READY_TO_LAND = "ready-to-land"
    CLEANUP_REQUIRED = "cleanup-required"
    COMPLETED = "completed"
    INVALIDATED = "invalidated"


class CapabilityClass(StrEnum):
    RESOLUTION = "resolution"
    EXECUTION = "execution"


class CapabilityName(StrEnum):
    INTENT_RESOLVE = "intent.resolve"
    WORKTREE_CREATE = "worktree.create"
    WORKTREE_WRITE = "worktree.write"
    VERIFICATION_RUN = "verification.run"
    CANDIDATE_CONVERGE = "candidate.converge"
    INTEGRATION_LAND = "integration.land"
    REMOTE_PUBLISH = "remote.publish"
    CHANGE_INVALIDATE = "change.invalidate"
    WORK_DISCARD = "work.discard"

    @property
    def capability_class(self) -> CapabilityClass:
        if self is CapabilityName.INTENT_RESOLVE:
            return CapabilityClass.RESOLUTION
        return CapabilityClass.EXECUTION


class DecisionState(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    NEEDS_AUTHORITY = "needs-authority"
    STALE = "stale"


class EnforcementPosture(StrEnum):
    MANAGED = "managed"
    ADVISORY = "advisory"
    NOT_APPLICABLE = "not-applicable"


class ActionKind(StrEnum):
    RECOMMEND_WORK = "recommend-work"
    RESOLVE_INTENT = "resolve-intent"
    REVIEW_SEMANTICS = "review-semantics"
    REVIEW_INDEPENDENT = "review-independent"
    ACCEPT_GOVERNANCE = "accept-governance"
    SUPPLY_INTENT = "supply-intent"


class DirectiveKind(StrEnum):
    DENY_CAPABILITY = "deny-capability"
    REQUIRE_RESOLUTION = "require-resolution"
    REQUIRE_REVIEW = "require-review"
    REQUIRE_VERIFIER = "require-verifier"
    SERIALIZE = "serialize"
    LIMIT_PARALLELISM = "limit-parallelism"
    REQUIRE_CONTAINMENT = "require-containment"


class ReviewMode(StrEnum):
    ATTRIBUTABLE = "attributable"
    INDEPENDENT = "independent"


class ReviewVerdict(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class EventKind(StrEnum):
    CHANGE_OPENED = "change.opened"
    RECOMMENDATION_REQUESTED = "recommendation.requested"
    RECOMMENDATION_RECORDED = "recommendation.recorded"
    RECOMMENDATION_REPLACED = "recommendation.replaced"
    ACTION_OPENED = "action.opened"
    ACTION_RESPONDED = "action.responded"
    DECISION_RECORDED = "decision.recorded"
    GRANT_ISSUED = "grant.issued"
    GRANT_REVOKED = "grant.revoked"
    GRANT_CONSUMED = "grant.consumed"
    ATTEMPT_CREATED = "attempt.created"
    ATTEMPT_SUBMITTED = "attempt.submitted"
    ATTEMPT_REJECTED = "attempt.rejected"
    UNIT_CONVERGED = "unit.converged"
    CANDIDATE_CONSTRUCTED = "candidate.constructed"
    CANDIDATE_EVIDENCED = "candidate.evidenced"
    CANDIDATE_REVIEWED = "candidate.reviewed"
    LANDING_STARTED = "landing.started"
    LANDING_COMPLETED = "landing.completed"
    LANDING_RECONCILED = "landing.reconciled"
    PUBLICATION_COMPLETED = "publication.completed"
    PUBLICATION_FAILED = "publication.failed"
    CHANGE_INVALIDATED = "change.invalidated"
    WORK_DISCARDED = "work.discarded"


AUTHORITY_LOCATOR = re.compile(
    r"(?:user|policy|record|agent|harness|kernel|design):[^\s\r\n]+"
)


def require_authority_locator(value: object, label: str = "authority") -> str:
    if not isinstance(value, str) or not AUTHORITY_LOCATOR.fullmatch(value):
        raise UsageError(f"{label} must be an attributable authority locator")
    return value


@dataclass(frozen=True)
class Intent:
    """One desired-state statement and the authority that supplied it."""

    statement: str
    supplier: str
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        statement = self.statement.strip()
        if not statement:
            raise UsageError("intent statement must be non-empty")
        object.__setattr__(self, "statement", statement)
        require_authority_locator(self.supplier, "intent supplier")
        object.__setattr__(
            self,
            "digest",
            digest({"statement": statement, "supplier": self.supplier}),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "statement": self.statement,
            "supplier": self.supplier,
            "digest": self.digest,
        }


def _coordinates(values: Sequence[str], prefix: str) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise UsageError(f"{prefix} scope contains an empty coordinate")
        item = value.strip()
        if prefix == "repo:":
            item = item.removeprefix("repo:").strip("/")
            if not item:
                item = "."
            if ".." in item.split("/"):
                raise UsageError("repository paths must stay below the repository root")
        else:
            item = item.removeprefix(prefix)
            require_id(item, f"{prefix} coordinate")
        normalized.add(f"{prefix}{item}")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class Scope:
    paths: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        paths: Sequence[str] = (),
        interfaces: Sequence[str] = (),
        domains: Sequence[str] = (),
        contracts: Sequence[str] = (),
    ) -> "Scope":
        return cls(
            _coordinates(paths, "repo:"),
            _coordinates(interfaces, "interface:"),
            _coordinates(domains, "domain:"),
            _coordinates(contracts, "contract:"),
        )

    @property
    def claims(self) -> tuple[str, ...]:
        return self.paths + self.interfaces + self.domains + self.contracts

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "paths": list(self.paths),
            "interfaces": list(self.interfaces),
            "domains": list(self.domains),
            "contracts": list(self.contracts),
        }


@dataclass(frozen=True)
class ProtocolResult:
    command: str
    outcome: Outcome
    result: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def envelope(self) -> dict[str, Any]:
        status = "ok"
        if self.outcome is Outcome.BLOCKED:
            status = "blocked"
        elif self.outcome is Outcome.FAILED:
            status = "error"
        return {
            "protocol": PROTOCOL_VERSION,
            "command": self.command,
            "status": status,
            "outcome": self.outcome.value,
            "result": dict(self.result),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }
