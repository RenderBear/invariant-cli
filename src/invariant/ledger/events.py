from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from invariant.errors import InvariantError
from invariant.protocol import (
    EventKind,
    PROTOCOL_VERSION,
    canonical_json,
    digest,
    require_authority_locator,
    require_id,
)


@dataclass(frozen=True)
class Event:
    version: int
    sequence: int
    operation_id: str
    request_digest: str
    kind: EventKind
    actor: str
    principal: str
    prior: str | None
    occurred_at: str
    payload: Mapping[str, Any]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        operation_id: str,
        kind: EventKind,
        actor: str,
        principal: str,
        prior: str | None,
        payload: Mapping[str, Any],
    ) -> "Event":
        require_id(operation_id, "operation id")
        require_authority_locator(actor, "event actor")
        require_authority_locator(principal, "transport principal")
        request_digest = digest(
            {
                "kind": kind.value,
                "actor": actor,
                "principal": principal,
                "payload": payload,
            }
        )
        body = {
            "version": PROTOCOL_VERSION,
            "sequence": sequence,
            "operation_id": operation_id,
            "request_digest": request_digest,
            "kind": kind.value,
            "actor": actor,
            "principal": principal,
            "prior": prior,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        return cls(
            PROTOCOL_VERSION,
            sequence,
            operation_id,
            request_digest,
            kind,
            actor,
            principal,
            prior,
            body["occurred_at"],
            deepcopy(dict(payload)),
            digest(body),
        )

    @classmethod
    def parse(cls, value: object) -> "Event":
        if not isinstance(value, dict):
            raise InvariantError("Invariant: corrupt ledger event", code="corrupt_ledger")
        allowed = {
            "version", "sequence", "operation_id", "request_digest", "kind", "actor",
            "principal", "prior", "occurred_at", "payload", "digest",
        }
        if value.get("version") != PROTOCOL_VERSION or set(value) != allowed:
            raise InvariantError("Invariant: invalid ledger event version", code="corrupt_ledger")
        try:
            kind = EventKind(value["kind"])
            require_id(value["operation_id"], "operation id")
            require_authority_locator(value["actor"], "event actor")
            require_authority_locator(value["principal"], "transport principal")
        except (ValueError, InvariantError) as exc:
            raise InvariantError(f"Invariant: invalid ledger event: {exc}", code="corrupt_ledger") from exc
        sequence = value["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise InvariantError("Invariant: invalid ledger sequence", code="corrupt_ledger")
        payload = value["payload"]
        if not isinstance(payload, dict):
            raise InvariantError("Invariant: invalid ledger payload", code="corrupt_ledger")
        body = {name: value[name] for name in allowed if name != "digest"}
        if digest(body) != value["digest"]:
            raise InvariantError("Invariant: ledger event digest mismatch", code="corrupt_ledger")
        expected_request = digest(
            {
                "kind": kind.value,
                "actor": value["actor"],
                "principal": value["principal"],
                "payload": payload,
            }
        )
        if expected_request != value["request_digest"]:
            raise InvariantError("Invariant: ledger request digest mismatch", code="corrupt_ledger")
        return cls(
            PROTOCOL_VERSION, sequence, value["operation_id"], value["request_digest"], kind,
            value["actor"], value["principal"], value["prior"], value["occurred_at"],
            payload, value["digest"],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sequence": self.sequence,
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
            "kind": self.kind.value,
            "actor": self.actor,
            "principal": self.principal,
            "prior": self.prior,
            "occurred_at": self.occurred_at,
            "payload": deepcopy(dict(self.payload)),
            "digest": self.digest,
        }


def _require(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    if not isinstance(value, dict):
        value = {}
        state[key] = value
    return value


def reduce_event(previous: Mapping[str, Any] | None, event: Event) -> dict[str, Any]:
    state: dict[str, Any] = deepcopy(dict(previous or {}))
    if event.kind is EventKind.CHANGE_OPENED:
        if previous:
            raise InvariantError("Invariant: duplicate change.opened event", code="corrupt_ledger")
        state = {
            "version": PROTOCOL_VERSION,
            "change": event.payload["change"],
            "intent": {**event.payload["intent"], "principal": event.principal},
            "repository": event.payload["repository"],
            "target": event.payload["target"],
            "base": event.payload["base"],
            "scope": event.payload["scope"],
            "governance": event.payload["governance"],
            "stage": "opened",
            "recommendation": None,
            "actions": {},
            "decisions": {},
            "grants": {},
            "attempts": {},
            "converged": [],
            "candidate": None,
            "evidence": [],
            "reviews": [],
            "landing": None,
            "publication": None,
            "invalidated": None,
            "operations": {},
        }
    elif not previous:
        raise InvariantError("Invariant: ledger does not begin with change.opened", code="corrupt_ledger")
    elif event.kind in {EventKind.RECOMMENDATION_RECORDED, EventKind.RECOMMENDATION_REPLACED}:
        state["recommendation"] = event.payload["recommendation"]
        state["stage"] = "ready"
    elif event.kind is EventKind.RECOMMENDATION_REQUESTED:
        state["stage"] = "recommending"
    elif event.kind is EventKind.ACTION_OPENED:
        action = deepcopy(event.payload["action"])
        action["status"] = "pending"
        _require(state, "actions")[action["id"]] = action
        if action.get("blocking", True):
            state["stage"] = "awaiting-action"
    elif event.kind is EventKind.ACTION_RESPONDED:
        actions = _require(state, "actions")
        action_id = event.payload["action"]
        if action_id not in actions or actions[action_id].get("status") != "pending":
            raise InvariantError("Invariant: action response has no pending action", code="corrupt_ledger")
        actions[action_id]["status"] = "responded"
        actions[action_id]["response"] = deepcopy(event.payload["response"])
        actions[action_id]["response"]["principal"] = event.principal
        actions[action_id]["response"]["event"] = event.digest
        state["stage"] = event.payload.get("next_stage", "evidencing")
    elif event.kind is EventKind.DECISION_RECORDED:
        decision = deepcopy(event.payload["decision"])
        decision["principal"] = event.principal
        _require(state, "decisions")[decision["id"]] = decision
    elif event.kind is EventKind.GRANT_ISSUED:
        grant = deepcopy(event.payload["grant"])
        grant["principal"] = event.principal
        grant["status"] = "live"
        _require(state, "grants")[grant["id"]] = grant
    elif event.kind in {EventKind.GRANT_REVOKED, EventKind.GRANT_CONSUMED}:
        grants = _require(state, "grants")
        grant_id = event.payload["grant"]
        if grant_id not in grants or grants[grant_id].get("status") != "live":
            raise InvariantError("Invariant: grant is not live", code="corrupt_ledger")
        grants[grant_id]["status"] = (
            "revoked" if event.kind is EventKind.GRANT_REVOKED else "consumed"
        )
        grants[grant_id]["closed_by"] = event.operation_id
    elif event.kind is EventKind.ATTEMPT_CREATED:
        attempt = deepcopy(event.payload["attempt"])
        attempt["principal"] = event.principal
        _require(state, "attempts")[attempt["id"]] = attempt
        state["stage"] = "executing"
    elif event.kind is EventKind.ATTEMPT_SUBMITTED:
        attempts = _require(state, "attempts")
        attempt_id = event.payload["attempt"]
        if attempt_id not in attempts:
            raise InvariantError("Invariant: submitted attempt is missing", code="corrupt_ledger")
        attempts[attempt_id].update(deepcopy(event.payload["result"]))
        attempts[attempt_id]["status"] = "submitted"
        state["stage"] = "converging"
    elif event.kind is EventKind.ATTEMPT_REJECTED:
        attempts = _require(state, "attempts")
        if event.payload["attempt"] in attempts:
            attempts[event.payload["attempt"]]["status"] = "rejected"
            attempts[event.payload["attempt"]]["rejection"] = event.payload["reason"]
    elif event.kind is EventKind.UNIT_CONVERGED:
        unit = event.payload["unit"]
        if unit not in state["converged"]:
            state["converged"].append(unit)
            state["converged"].sort()
        state["stage"] = "converging"
    elif event.kind is EventKind.CANDIDATE_CONSTRUCTED:
        state["candidate"] = deepcopy(event.payload["candidate"])
        recommendation = state.get("recommendation") or {}
        units = {item["id"] for item in recommendation.get("units", [])}
        state["stage"] = "evidencing" if units == set(state["converged"]) else "ready"
        state["evidence"] = []
        state["reviews"] = []
    elif event.kind is EventKind.CANDIDATE_EVIDENCED:
        state["evidence"] = deepcopy(event.payload["evidence"])
        state["governance"] = {
            **deepcopy(event.payload["governance"]),
            "obligations": deepcopy(event.payload["obligations"]),
        }
        state["stage"] = event.payload.get("next_stage", "ready-to-land")
    elif event.kind is EventKind.CANDIDATE_REVIEWED:
        review = deepcopy(event.payload["review"])
        review["principal"] = event.principal
        state["reviews"].append(review)
        state["stage"] = event.payload.get("next_stage", "ready-to-land")
    elif event.kind is EventKind.LANDING_STARTED:
        state["landing"] = deepcopy(event.payload["landing"])
        state["stage"] = "cleanup-required"
    elif event.kind in {EventKind.LANDING_COMPLETED, EventKind.LANDING_RECONCILED}:
        completed = event.payload.get("completed", True)
        landing = {
            **(state.get("landing") or {}),
            **deepcopy(event.payload["landing"]),
        }
        if completed:
            landing["event"] = event.digest
            landing["sequence"] = event.sequence
        state["landing"] = landing
        state["stage"] = "completed" if completed else "ready-to-land"
    elif event.kind in {EventKind.PUBLICATION_COMPLETED, EventKind.PUBLICATION_FAILED}:
        state["publication"] = deepcopy(event.payload["publication"])
    elif event.kind is EventKind.CHANGE_INVALIDATED:
        state["invalidated"] = deepcopy(event.payload)
        state["stage"] = "invalidated"
    elif event.kind is EventKind.WORK_DISCARDED:
        state["discarded"] = deepcopy(event.payload)

    operations = _require(state, "operations")
    existing = operations.get(event.operation_id)
    if existing and existing["request_digest"] != event.request_digest:
        raise InvariantError("Invariant: operation id was reused", code="corrupt_ledger")
    operations[event.operation_id] = {
        "request_digest": event.request_digest,
        "event_digest": event.digest,
        "sequence": event.sequence,
        "principal": event.principal,
    }
    state["sequence"] = event.sequence
    state["last_event"] = event.digest
    return state


def serialized(value: Mapping[str, Any]) -> str:
    return canonical_json(value) + "\n"
