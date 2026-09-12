from __future__ import annotations

from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.ledger.store import LedgerStore
from invariant.mechanics import git
from invariant.protocol import PROTOCOL_VERSION, canonical_json, digest


def create(store: LedgerStore, change_id: str) -> dict[str, Any]:
    ledger = store.load(change_id)
    state = ledger.state
    work = sorted(
        (
            {
                "attempt": attempt["id"],
                "ref": attempt["ref"],
                "tip": git.resolve(store.repository.root, attempt["ref"]),
                "status": attempt["status"],
            }
            for attempt in state.get("attempts", {}).values()
        ),
        key=lambda item: item["attempt"],
    )
    candidate = state.get("candidate")
    object_ids = {
        ledger.head,
        state["base"],
        *(item["tip"] for item in work if item["tip"]),
        *([candidate["commit"]] if candidate else []),
    }
    capsule = {
        "version": PROTOCOL_VERSION,
        "repository": store.repository.identity,
        "change": change_id,
        "ledger": ledger.head,
        "intent": state["intent"]["digest"],
        "target": state["target"],
        "base": state["base"],
        "stage": state["stage"],
        "recommendation": (
            {
                "id": state["recommendation"]["id"],
                "digest": state["recommendation"]["digest"],
            }
            if state.get("recommendation")
            else None
        ),
        "work": work,
        "candidate": candidate,
        "pending_actions": sorted(
            action["id"]
            for action in state.get("actions", {}).values()
            if action.get("status") == "pending"
        ),
        "live_grants": sorted(
            (
                {
                    "id": grant["id"],
                    "class": grant["class"],
                    "capability": grant["capability"],
                    "actor": grant["actor"],
                    "resource": grant["resource"],
                }
                for grant in state.get("grants", {}).values()
                if grant.get("status") == "live"
            ),
            key=lambda item: item["id"],
        ),
        "objects": sorted(object_ids),
    }
    capsule["digest"] = digest(capsule)
    return capsule


def validate(store: LedgerStore, capsule: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(capsule, dict) or capsule.get("version") != PROTOCOL_VERSION:
        raise InvariantError("Invariant: invalid handoff capsule", code="invalid_invocation")
    supplied = dict(capsule)
    supplied_digest = supplied.pop("digest", None)
    if supplied_digest != digest(supplied):
        raise InvariantError("Invariant: handoff digest mismatch", code="invalid_invocation")
    if supplied.get("repository") != store.repository.identity:
        raise InvariantError("Invariant: handoff belongs to another repository", code="invalid_invocation")
    ledger = store.load(str(supplied.get("change", "")))
    if supplied.get("ledger") != ledger.head:
        raise Blocked(
            "Invariant: handoff is stale; use the current ledger",
            code="stale_handoff",
            data={"supplied": supplied.get("ledger"), "current": ledger.head},
        )
    if supplied.get("intent") != ledger.state["intent"]["digest"]:
        raise InvariantError("Invariant: handoff intent mismatch", code="corrupt_ledger")
    current = create(store, ledger.change_id)
    if canonical_json(capsule) != canonical_json(current):
        raise Blocked(
            "Invariant: handoff no longer matches durable change state",
            code="stale_handoff",
            data={"current": current},
        )
    for object_id in current["objects"]:
        if not git.resolve(store.repository.root, object_id):
            raise InvariantError(
                f"Invariant: handoff object '{object_id}' is missing",
                code="missing_object",
            )
    return current
