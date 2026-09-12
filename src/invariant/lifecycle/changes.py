from __future__ import annotations

from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.gateway import CapabilityService
from invariant.governance import GovernanceStore, compile_obligations, select
from invariant.ledger import Ledger, LedgerStore
from invariant.ledger import handoff
from invariant.mechanics import git
from invariant.planning import RecommendationService
from invariant.protocol import (
    CapabilityName,
    EventKind,
    Intent,
    Scope,
    is_direct_user_authority,
    require_id,
)


class ChangeService:
    def __init__(
        self,
        store: LedgerStore,
        capabilities: CapabilityService,
        recommendations: RecommendationService,
    ) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities
        self.recommendations = recommendations

    def open(
        self,
        change_id: str,
        *,
        statement: str,
        supplier: str,
        scope: Scope,
        operation_id: str,
    ) -> Ledger:
        require_id(change_id, "change id")
        intent = Intent(statement, supplier)
        current_policy = self.repository.policy
        target = current_policy.integration_branch
        base = git.resolve(self.repository.root, f"refs/heads/{target}")
        if not base:
            raise Blocked(
                "Invariant: initialization requires a committed integration base",
                code="not_initialized",
            )
        policy = self.repository.policy_at(base, target)
        if policy.integration_branch != target:
            raise Blocked(
                "Invariant: integration target differs from accepted tracked policy",
                code="stale_policy",
                data={"requested": target, "accepted": policy.integration_branch},
            )
        if not policy.authority.intent.permits(supplier):
            raise InvariantError(
                f"Invariant: policy does not accept intent supplied by '{supplier}'",
                code="authority_required",
            )
        if supplier.startswith("user:") and not is_direct_user_authority(
            supplier, self.store.principal
        ):
            raise InvariantError(
                "Invariant: user intent must match the transport principal",
                code="authority_required",
            )
        governance = GovernanceStore(self.repository.primary_worktree).load(base)
        selection = select(governance, scope)
        obligations = compile_obligations(policy, selection, scope)
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.CHANGE_OPENED,
            actor=supplier,
            payload={
                "change": change_id,
                "intent": intent.as_dict(),
                "repository": self.repository.identity,
                "target": {"branch": target, "ref": f"refs/heads/{target}"},
                "base": base,
                "scope": scope.as_dict(),
                "governance": {
                    **selection.as_dict(),
                    "obligations": obligations.as_dict(),
                },
            },
            expected_head=None,
            anchors=[base],
        )

    def recommend(
        self,
        change_id: str,
        *,
        operation_id: str,
        host_capacity: int | None = None,
    ) -> Ledger:
        ledger = self.store.load(change_id)
        if ledger.state.get("recommendation"):
            return ledger
        requested = self.store.append(
            change_id,
            operation_id=f"{operation_id}.request",
            kind=EventKind.RECOMMENDATION_REQUESTED,
            actor="kernel:repository/planning",
            payload={"change": change_id, "intent": ledger.state["intent"]["digest"]},
            expected_head=ledger.head,
        )
        # Recompile from accepted state rather than trusting serialized fields.
        scope_raw = requested.state["scope"]
        scope = Scope.create(
            paths=scope_raw["paths"], interfaces=scope_raw["interfaces"],
            domains=scope_raw["domains"], contracts=scope_raw["contracts"],
        )
        governance = GovernanceStore(self.repository.primary_worktree).load(requested.state["base"])
        selection = select(governance, scope)
        policy = self.repository.policy_at(
            requested.state["base"], requested.state["target"]["branch"]
        )
        obligations = compile_obligations(policy, selection, scope)
        recommendation = self.recommendations.recommend(
            change=change_id,
            base=requested.state["base"],
            intent=requested.state["intent"],
            scope=requested.state["scope"],
            governance=selection.as_dict(),
            obligations=obligations,
            policy_limit=policy.parallelism.limit(host_capacity),
            host_capacity=host_capacity,
        )
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.RECOMMENDATION_RECORDED,
            actor="kernel:repository/planning",
            payload={"recommendation": recommendation.as_dict()},
            expected_head=requested.head,
        )

    def inspect(self, change_id: str) -> dict[str, Any]:
        ledger = self.store.load(change_id)
        state = self._redacted(dict(ledger.state))
        state["ledger"] = ledger.head
        state["frontier"] = list(self.capabilities._frontier(ledger.state))
        state["assurance"] = {
            "authorization": "evaluated",
            "execution_enforcement": "advisory",
            "authority_model": "supplied-intent + scoped-resolution",
        }
        return state

    def handoff(self, change_id: str) -> dict[str, Any]:
        return handoff.create(self.store, change_id)

    def resume(
        self,
        capsule: Mapping[str, Any],
        *,
        actor: str,
        operation_id: str,
    ) -> Ledger:
        validated = handoff.validate(self.store, capsule)
        ledger = self.store.load(str(capsule["change"]))
        if capsule["ledger"] != ledger.head:
            raise Blocked(
                "Invariant: handoff is stale; current state is safe to inspect",
                code="stale_handoff",
                data={"capsule": capsule["ledger"], "current": ledger.head},
            )
        current = ledger
        live = [
            grant for grant in current.state.get("grants", {}).values()
            if grant.get("status") == "live"
        ]
        for index, grant in enumerate(live):
            current = self.capabilities.revoke(
                current.change_id,
                grant["id"],
                actor=actor,
                operation_id=f"{operation_id}.revoke{index}",
                reason="handoff resumed without bearer tokens",
            )
        return current

    def invalidate(
        self,
        change_id: str,
        *,
        token: str,
        actor: str,
        reason: str,
        operation_id: str,
    ) -> Ledger:
        existing = self.store.load(change_id)
        replay = existing.event_for(operation_id)
        if replay:
            if replay.kind is EventKind.CHANGE_INVALIDATED:
                return existing
            raise InvariantError(
                "Invariant: operation id was reused with different invalidation input",
                code="invalid_invocation",
            )
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.CHANGE_INVALIDATE,
            resource=change_id,
            operation_id=operation_id,
        )
        consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.CHANGE_INVALIDATED,
            actor=actor,
            payload={"reason": reason, "actor": actor},
            expected_head=consumed.head,
        )

    @classmethod
    def _redacted(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._redacted(item)
                for key, item in value.items()
                if key != "token_digest"
            }
        if isinstance(value, list):
            return [cls._redacted(item) for item in value]
        return value
