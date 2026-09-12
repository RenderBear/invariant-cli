from __future__ import annotations

from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.gateway import CapabilityService
from invariant.ledger import Ledger, LedgerStore
from invariant.protocol import (
    ActionKind,
    CapabilityName,
    EventKind,
    ReviewMode,
    ReviewVerdict,
    digest,
    is_direct_user_authority,
    require_authority_locator,
)


class ActionService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.capabilities = capabilities

    def inspect(self, change_id: str, action_id: str) -> dict[str, Any]:
        ledger = self.store.load(change_id)
        action = ledger.state.get("actions", {}).get(action_id)
        if not action:
            raise InvariantError(f"Invariant: unknown action '{action_id}'", code="invalid_invocation")
        return {"ledger": ledger.head, "action": action}

    def respond(
        self,
        change_id: str,
        action_id: str,
        *,
        response: Mapping[str, Any],
        actor: str,
        operation_id: str,
        token: str | None = None,
    ) -> Ledger:
        require_authority_locator(actor, "response actor")
        ledger = self.store.load(change_id)
        replay = ledger.event_for(operation_id)
        normalized = {
            **dict(response),
            "actor": actor,
            "principal": self.store.principal,
        }
        if replay:
            if (
                replay.kind is EventKind.ACTION_RESPONDED
                and replay.payload.get("action") == action_id
                and replay.payload.get("response") == normalized
            ):
                return ledger
            raise InvariantError(
                "Invariant: operation id was reused with different action input",
                code="invalid_invocation",
            )
        action = ledger.state.get("actions", {}).get(action_id)
        if not action or action.get("status") != "pending":
            raise Blocked("Invariant: action is no longer pending", code="stale_grant")
        if response.get("bindings") != action.get("bindings"):
            raise Blocked("Invariant: action response bindings are stale", code="stale_review")
        bindings = action["bindings"]
        state = ledger.state
        if (
            bindings.get("intent") != state["intent"]["digest"]
            or bindings.get("candidate") != (state.get("candidate") or {}).get("tree")
        ):
            raise Blocked("Invariant: action causal state changed", code="stale_review")

        kind = ActionKind(action["kind"])
        policy = self.store.repository.policy_at(
            state["base"], state["target"]["branch"]
        )
        direct_user_intent = (
            is_direct_user_authority(actor, self.store.principal)
            and policy.authority.intent.permits(actor)
            and token is None
        )
        if kind in {ActionKind.ACCEPT_GOVERNANCE, ActionKind.SUPPLY_INTENT} and not direct_user_intent:
            raise InvariantError("Invariant: this action requires direct user intent", code="authority_required")
        review_values: tuple[ReviewVerdict, ReviewMode, str] | None = None
        if kind in {ActionKind.REVIEW_SEMANTICS, ActionKind.REVIEW_INDEPENDENT}:
            try:
                verdict = ReviewVerdict(str(response.get("verdict")))
            except ValueError as exc:
                raise InvariantError("Invariant: review verdict is invalid", code="invalid_invocation") from exc
            expected_mode = (
                ReviewMode.INDEPENDENT
                if kind is ActionKind.REVIEW_INDEPENDENT else ReviewMode.ATTRIBUTABLE
            )
            summary = response.get("summary")
            if verdict is ReviewVerdict.ACCEPTED and (
                not isinstance(summary, str) or not summary.strip()
            ):
                raise InvariantError("Invariant: accepted review requires a summary", code="invalid_invocation")
            authors = {attempt.get("actor") for attempt in state.get("attempts", {}).values()}
            author_principals = {
                attempt.get("principal") for attempt in state.get("attempts", {}).values()
            }
            if expected_mode is ReviewMode.INDEPENDENT and (
                actor in authors or self.store.principal in author_principals
            ):
                raise InvariantError(
                    "Invariant: an author cannot mark its own work independent",
                    code="independent_review_required",
                )
            review_values = (verdict, expected_mode, str(summary or ""))
        elif (
            kind in {ActionKind.RESOLVE_INTENT, ActionKind.ACCEPT_GOVERNANCE}
            and response.get("resolution") not in {"accepted", "rejected"}
        ):
            raise InvariantError(
                "Invariant: intent resolution must be accepted or rejected",
                code="invalid_invocation",
            )
        elif kind is ActionKind.SUPPLY_INTENT and response.get("resolution") != "accepted":
            raise InvariantError(
                "Invariant: supplied intent must explicitly accept the resolution",
                code="invalid_invocation",
            )
        current = ledger
        if not direct_user_intent:
            if not token:
                raise InvariantError("Invariant: resolution capability is required", code="capability_required")
            use = self.capabilities.use(
                change_id,
                token=token,
                capability=CapabilityName.INTENT_RESOLVE,
                resource=action_id,
                operation_id=operation_id,
            )
            if use.grant.get("actor") != actor:
                raise InvariantError(
                    "Invariant: resolution grant belongs to another actor",
                    code="capability_required",
                )
            current = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")

        responded = self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.ACTION_RESPONDED,
            actor=actor,
            payload={
                "action": action_id,
                "response": normalized,
                "next_stage": action.get("resume_stage", "evidencing"),
            },
            expected_head=current.head,
        )
        if kind not in {ActionKind.REVIEW_SEMANTICS, ActionKind.REVIEW_INDEPENDENT}:
            return responded
        assert review_values is not None
        verdict, expected_mode, summary = review_values
        if verdict is not ReviewVerdict.ACCEPTED:
            return responded
        review_body = {
            "action": action_id,
            "candidate": bindings["candidate"],
            "evidence": bindings["evidence"],
            "intent": bindings["intent"],
            "verdict": verdict.value,
            "mode": expected_mode.value,
            "authority": actor,
            "principal": self.store.principal,
            "summary": summary.strip(),
            "defects": response.get("defects", []),
        }
        review = {**review_body, "digest": digest(review_body)}
        return self.store.append(
            change_id,
            operation_id=f"{operation_id}.review",
            kind=EventKind.CANDIDATE_REVIEWED,
            actor=actor,
            payload={"review": review, "next_stage": "ready-to-land"},
            expected_head=responded.head,
        )
