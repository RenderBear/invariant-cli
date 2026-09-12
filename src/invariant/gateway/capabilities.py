from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import secrets
from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.gateway.containment import Enforcement, Uncontained
from invariant.governance import GovernanceStore, compile_obligations, select
from invariant.ledger import Ledger, LedgerStore
from invariant.mechanics import git
from invariant.protocol import (
    ActionKind,
    CapabilityName,
    DecisionState,
    EnforcementPosture,
    EventKind,
    Outcome,
    Scope,
    digest,
    is_direct_user_authority,
    require_authority_locator,
    require_id,
)


@dataclass(frozen=True)
class CapabilityResult:
    outcome: Outcome
    decision: Mapping[str, Any]
    grant: Mapping[str, Any] | None = None
    token: str | None = None
    action: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"decision": dict(self.decision)}
        if self.grant:
            value["grant"] = {key: item for key, item in self.grant.items() if key != "token_digest"}
        if self.token:
            value["token"] = self.token
        if self.action:
            value["action"] = dict(self.action)
        return value


@dataclass(frozen=True)
class GrantUse:
    ledger: Ledger
    grant: Mapping[str, Any]


class CapabilityService:
    def __init__(self, store: LedgerStore, containment: Uncontained | None = None) -> None:
        self.store = store
        self.repository = store.repository
        self.containment = containment or Uncontained()

    def request(
        self,
        change_id: str,
        *,
        capability: CapabilityName | str,
        actor: str,
        resource: str,
        operation_id: str,
        expected_ledger: str | None = None,
        unit: str | None = None,
        attempt: str | None = None,
        reason: str | None = None,
    ) -> CapabilityResult:
        try:
            name = capability if isinstance(capability, CapabilityName) else CapabilityName(capability)
        except ValueError as exc:
            raise InvariantError(f"Invariant: unknown capability '{capability}'", code="unknown_capability") from exc
        require_authority_locator(actor, "capability actor")
        require_id(operation_id, "operation id")
        ledger = self.store.load(change_id)
        replay = ledger.event_for(operation_id)
        if replay:
            if replay.kind is not EventKind.DECISION_RECORDED:
                raise InvariantError(
                    "Invariant: operation id was reused for another consequence",
                    code="invalid_invocation",
                )
            prior = replay.payload["decision"]
            expected_request = {
                "capability": name.value,
                "actor": actor,
                "principal": self.store.principal,
                "change": change_id,
                "unit": unit,
                "attempt": attempt,
                "resource": resource,
                "expected_ledger": expected_ledger,
                "reason": reason,
            }
            if prior.get("request") != expected_request:
                raise InvariantError(
                    "Invariant: operation id was reused with different input",
                    code="invalid_invocation",
                )
            grant = next(
                (
                    item
                    for item in ledger.state.get("grants", {}).values()
                    if item.get("decision") == prior["id"]
                ),
                None,
            )
            action = next(
                (
                    item
                    for item in ledger.state.get("actions", {}).values()
                    if item.get("context", {}).get("decision") == prior["id"]
                ),
                None,
            )
            outcome = {
                DecisionState.GRANTED.value: Outcome.READY,
                DecisionState.DENIED.value: Outcome.DENIED,
                DecisionState.NEEDS_AUTHORITY.value: Outcome.NEEDS_INPUT,
                DecisionState.STALE.value: Outcome.STALE,
            }[prior["state"]]
            public_grant = (
                {key: value for key, value in grant.items() if key != "token_digest"}
                if grant
                else None
            )
            return CapabilityResult(outcome, prior, public_grant, action=action)
        policy = self.repository.policy_at(
            ledger.state["base"], ledger.state["target"]["branch"]
        )
        scope_raw = ledger.state.get("scope", {})
        candidate_paths = (ledger.state.get("candidate") or {}).get("paths", [])
        scope = Scope.create(
            paths=(*scope_raw.get("paths", []), *candidate_paths),
            interfaces=scope_raw.get("interfaces", []),
            domains=scope_raw.get("domains", []),
            contracts=scope_raw.get("contracts", []),
        )
        governance = GovernanceStore(self.repository.primary_worktree).load(ledger.state["base"])
        selection = select(governance, scope, name)
        obligations = compile_obligations(policy, selection, scope)
        enforcement = self.containment.evaluate(name, resource)
        required_resolver = obligations.required_resolution.get(name.value)
        state, explanation = self._evaluate(
            ledger, name, actor, resource, unit, attempt, reason,
            expected_ledger, obligations.denied_by(name),
            required_resolver,
            obligations.containment.get(name.value),
            enforcement,
            policy.authority.resolution.delegation,
        )
        decision_body = {
            "capability": name.value,
            "class": name.capability_class.value,
            "actor": actor,
            "principal": self.store.principal,
            "change": change_id,
            "unit": unit,
            "attempt": attempt,
            "resource": resource,
            "request": {
                "capability": name.value,
                "actor": actor,
                "principal": self.store.principal,
                "change": change_id,
                "unit": unit,
                "attempt": attempt,
                "resource": resource,
                "expected_ledger": expected_ledger,
                "reason": reason,
            },
            "requested_at": ledger.head,
            "scope": scope.as_dict(),
            "governance": selection.digest,
            "state": state.value,
            "enforcement": enforcement.as_dict(),
            "explain": {
                "reason": explanation,
                "sources": list(obligations.sources),
                "obligations": obligations.as_dict(),
            },
        }
        decision_digest = digest(decision_body)
        decision = {
            "id": f"decision-{decision_digest[:20]}",
            **decision_body,
            "digest": decision_digest,
        }
        recorded = self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.DECISION_RECORDED,
            actor="kernel:repository/capability",
            payload={"decision": decision},
            expected_head=ledger.head,
        )
        if state is not DecisionState.GRANTED:
            outcome = {
                DecisionState.DENIED: Outcome.DENIED,
                DecisionState.NEEDS_AUTHORITY: Outcome.NEEDS_INPUT,
                DecisionState.STALE: Outcome.STALE,
            }[state]
            action = None
            if state is DecisionState.NEEDS_AUTHORITY and required_resolver:
                action, recorded = self._open_resolution_action(
                    recorded, name, required_resolver, decision, operation_id
                )
            return CapabilityResult(outcome, decision, action=action)

        token = secrets.token_urlsafe(32)
        token_digest = sha256(token.encode("utf-8")).hexdigest()
        grant_body = {
            "decision": decision["id"],
            "decision_digest": decision_digest,
            "capability": name.value,
            "class": name.capability_class.value,
            "actor": actor,
            "principal": self.store.principal,
            "change": change_id,
            "unit": unit,
            "attempt": attempt,
            "resource": resource,
            "target": ledger.state["target"],
            "base": ledger.state["base"],
            "intent": ledger.state["intent"]["digest"],
            "governance": selection.digest,
            "candidate": (ledger.state.get("candidate") or {}).get("tree"),
            "token_digest": token_digest,
            "single_use": name not in {CapabilityName.WORKTREE_WRITE},
            "enforcement": enforcement.as_dict(),
        }
        grant_digest = digest(grant_body)
        grant = {"id": f"grant-{grant_digest[:20]}", **grant_body, "digest": grant_digest}
        issued = self.store.append(
            change_id,
            operation_id=f"{operation_id}.grant",
            kind=EventKind.GRANT_ISSUED,
            actor="kernel:repository/capability",
            payload={"grant": grant},
            expected_head=recorded.head,
        )
        public = {key: value for key, value in issued.state["grants"][grant["id"]].items() if key != "token_digest"}
        return CapabilityResult(Outcome.READY, decision, public, token)

    def inspect(self, change_id: str, identifier: str) -> dict[str, Any]:
        ledger = self.store.load(change_id)
        if identifier in ledger.state.get("decisions", {}):
            return {"ledger": ledger.head, "decision": ledger.state["decisions"][identifier]}
        if identifier in ledger.state.get("grants", {}):
            grant = ledger.state["grants"][identifier]
            return {"ledger": ledger.head, "grant": {key: value for key, value in grant.items() if key != "token_digest"}}
        raise InvariantError(f"Invariant: unknown decision or grant '{identifier}'", code="invalid_invocation")

    def use(
        self,
        change_id: str,
        *,
        token: str,
        capability: CapabilityName,
        resource: str,
        operation_id: str,
    ) -> GrantUse:
        ledger = self.store.load(change_id)
        token_digest = sha256(token.encode("utf-8")).hexdigest()
        matches = [
            grant for grant in ledger.state.get("grants", {}).values()
            if secrets.compare_digest(str(grant.get("token_digest", "")), token_digest)
        ]
        if len(matches) != 1:
            raise InvariantError("Invariant: capability grant is required", code="capability_required")
        grant = matches[0]
        if grant.get("status") != "live":
            code = "grant_consumed" if grant.get("status") == "consumed" else "grant_revoked"
            raise InvariantError(f"Invariant: grant is {grant.get('status')}", code=code)
        if grant.get("capability") != capability.value or grant.get("resource") != resource:
            raise InvariantError("Invariant: grant does not match this consequence", code="capability_required")
        state = ledger.state
        if state.get("intent", {}).get("digest") != grant.get("intent"):
            raise Blocked("Invariant: grant intent is stale", code="stale_grant")
        candidate = state.get("candidate") or {}
        if grant.get("candidate") and grant.get("candidate") != candidate.get("tree"):
            raise Blocked("Invariant: grant candidate is stale", code="stale_grant")
        return GrantUse(ledger, grant)

    def consume(self, use: GrantUse, *, operation_id: str) -> Ledger:
        return self.store.append(
            use.ledger.change_id,
            operation_id=operation_id,
            kind=EventKind.GRANT_CONSUMED,
            actor="kernel:repository/capability",
            payload={"grant": use.grant["id"]},
            expected_head=use.ledger.head,
        )

    def revoke(self, change_id: str, grant_id: str, *, actor: str, operation_id: str, reason: str) -> Ledger:
        ledger = self.store.load(change_id)
        grant = ledger.state.get("grants", {}).get(grant_id)
        if not grant:
            raise InvariantError(f"Invariant: unknown grant '{grant_id}'", code="invalid_invocation")
        if grant.get("status") != "live":
            return ledger
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.GRANT_REVOKED,
            actor=actor,
            payload={"grant": grant_id, "reason": reason},
            expected_head=ledger.head,
        )

    def _evaluate(
        self,
        ledger: Ledger,
        name: CapabilityName,
        actor: str,
        resource: str,
        unit: str | None,
        attempt: str | None,
        reason: str | None,
        expected: str | None,
        denied_by: tuple[str, ...],
        required_resolver: str | None,
        required_containment: str | None,
        enforcement: Enforcement,
        resolution_delegation: str,
    ) -> tuple[DecisionState, str]:
        state = ledger.state
        if expected is not None and expected != ledger.head:
            return DecisionState.STALE, "the supplied ledger head moved"
        if denied_by:
            return DecisionState.DENIED, "denied by " + ", ".join(denied_by)
        if required_containment == "managed" and enforcement.posture is not EnforcementPosture.MANAGED:
            return DecisionState.DENIED, "managed containment is required but unavailable"
        if state.get("stage") == "invalidated" and name is not CapabilityName.WORK_DISCARD:
            return DecisionState.DENIED, "the change is invalidated"
        if required_resolver and not self._has_resolution(state, name, required_resolver):
            return DecisionState.NEEDS_AUTHORITY, f"{required_resolver} resolution is required"
        if name is CapabilityName.INTENT_RESOLVE:
            action = state.get("actions", {}).get(resource)
            if not action or action.get("status") != "pending":
                return DecisionState.STALE, "the bound action is not pending"
            kind = action.get("kind")
            direct_user = is_direct_user_authority(actor, self.store.principal)
            if (
                kind == ActionKind.SUPPLY_INTENT.value
                and not direct_user
            ):
                return DecisionState.NEEDS_AUTHORITY, "fresh user intent is required"
            if kind == ActionKind.ACCEPT_GOVERNANCE.value and not direct_user:
                if (
                    action.get("resolver") != "secondary-agent"
                    or not actor.startswith("agent:")
                ):
                    return (
                        DecisionState.NEEDS_AUTHORITY,
                        "governance acceptance requires its configured resolver",
                    )
                authors = {
                    item.get("actor") for item in state.get("attempts", {}).values()
                }
                principals = {
                    item.get("principal") for item in state.get("attempts", {}).values()
                }
                if actor in authors or self.store.principal in principals:
                    return (
                        DecisionState.NEEDS_AUTHORITY,
                        "governance acceptance requires a distinct secondary agent",
                    )
            if actor.startswith("agent:") and resolution_delegation != "secondary-agent":
                return (
                    DecisionState.NEEDS_AUTHORITY,
                    "policy does not delegate resolution to a secondary agent",
                )
        elif name is CapabilityName.WORKTREE_CREATE:
            if not unit or unit not in self._frontier(state):
                return DecisionState.STALE, "the unit is outside the current admissible frontier"
        elif name is CapabilityName.WORKTREE_WRITE:
            if not attempt or attempt not in state.get("attempts", {}):
                return DecisionState.STALE, "the attempt does not exist"
        elif name is CapabilityName.VERIFICATION_RUN:
            if not state.get("candidate"):
                return DecisionState.STALE, "there is no exact candidate"
        elif name is CapabilityName.CANDIDATE_CONVERGE:
            candidate = state.get("attempts", {}).get(attempt or "")
            if not candidate or candidate.get("status") != "submitted":
                return DecisionState.STALE, "the attempt is not submitted"
        elif name is CapabilityName.INTEGRATION_LAND:
            if state.get("stage") != "ready-to-land" or not state.get("candidate"):
                return DecisionState.STALE, "candidate obligations are not satisfied"
        elif name is CapabilityName.REMOTE_PUBLISH:
            if state.get("stage") != "completed" or not state.get("landing"):
                return DecisionState.STALE, "local landing is not complete"
        elif name is CapabilityName.CHANGE_INVALIDATE:
            if not reason:
                return DecisionState.NEEDS_AUTHORITY, "invalidation requires an attributable reason"
        elif name is CapabilityName.WORK_DISCARD and not (
            is_direct_user_authority(actor, self.store.principal)
            and self.repository.policy_at(
                state["base"], state["target"]["branch"]
            ).authority.intent.permits(actor)
        ):
            return DecisionState.NEEDS_AUTHORITY, "discard requires fresh user intent"
        return DecisionState.GRANTED, "current intent, governance, and causal state permit this consequence"

    @staticmethod
    def _has_resolution(state: Mapping[str, Any], capability: CapabilityName, resolver: str) -> bool:
        for action in state.get("actions", {}).values():
            response = action.get("response", {})
            actor = response.get("actor", "") if isinstance(response, dict) else ""
            principal = response.get("principal", "") if isinstance(response, dict) else ""
            accepted = response.get("resolution") == "accepted" or response.get("verdict") == "accepted"
            if action.get("for_capability") == capability.value and action.get("status") == "responded" and accepted:
                if is_direct_user_authority(actor, principal):
                    return True
                if resolver == "any-attributable" or (
                    resolver == "secondary-agent" and actor.startswith("agent:")
                ):
                    return True
        return False

    def _open_resolution_action(
        self,
        ledger: Ledger,
        capability: CapabilityName,
        resolver: str,
        decision: Mapping[str, Any],
        operation_id: str,
    ) -> tuple[Mapping[str, Any], Ledger]:
        existing = next(
            (
                action
                for action in ledger.state.get("actions", {}).values()
                if action.get("for_capability") == capability.value
                and action.get("status") == "pending"
            ),
            None,
        )
        if existing:
            return existing, ledger
        state = ledger.state
        candidate = state.get("candidate") or {}
        action_id = f"resolve-{capability.value.replace('.', '-')}-{decision['digest'][:12]}"
        governance_change = any(
            path.removeprefix("repo:") == ".invariant/config.yml"
            or path.removeprefix("repo:").startswith(".invariant/records/")
            for path in candidate.get("paths", [])
        ) or "protocol:governance-acceptance" in decision["explain"]["sources"]
        kind = (
            ActionKind.ACCEPT_GOVERNANCE.value
            if governance_change and capability is CapabilityName.INTEGRATION_LAND
            else (
                ActionKind.SUPPLY_INTENT.value
                if resolver == "user"
                else ActionKind.RESOLVE_INTENT.value
            )
        )
        action = {
            "id": action_id,
            "kind": kind,
            "schema": f"invariant://v1/actions/{kind}",
            "blocking": True,
            "for_capability": capability.value,
            "resolver": resolver,
            "resume_stage": state["stage"],
            "bindings": {
                "change": ledger.change_id,
                "ledger": ledger.head,
                "intent": state["intent"]["digest"],
                "supplier": state["intent"]["supplier"],
                "recommendation": (state.get("recommendation") or {}).get("digest"),
                "candidate": candidate.get("tree"),
                "governance": decision["governance"],
                "evidence": digest(state.get("evidence", [])),
            },
            "context": {
                "capability": capability.value,
                "decision": decision["id"],
                "intent": state["intent"],
                "scope": decision["scope"],
                "governance": decision["governance"],
                "candidate": candidate,
                "evidence": state.get("evidence", []),
            },
        }
        updated = self.store.append(
            ledger.change_id,
            operation_id=f"{operation_id}.action",
            kind=EventKind.ACTION_OPENED,
            actor="kernel:repository/semantic",
            payload={"action": action},
            expected_head=ledger.head,
        )
        return updated.state["actions"][action_id], updated

    @staticmethod
    def _frontier(state: Mapping[str, Any]) -> tuple[str, ...]:
        recommendation = state.get("recommendation") or {}
        done = set(state.get("converged", []))
        live = {
            grant.get("unit") for grant in state.get("grants", {}).values()
            if grant.get("capability") == CapabilityName.WORKTREE_WRITE.value and grant.get("status") == "live"
        }
        units = recommendation.get("units", [])
        ready = [
            unit["id"] for unit in units
            if unit["id"] not in done and unit["id"] not in live and set(unit.get("depends_on", [])) <= done
        ]
        conflicts = {tuple(sorted(pair)) for pair in recommendation.get("conflicts", [])}
        result: list[str] = []
        limit = int(recommendation.get("maximum_parallelism", 1)) - len(live)
        for candidate in ready:
            if len(result) >= max(0, limit):
                break
            if all(tuple(sorted((candidate, item))) not in conflicts for item in (*live, *result)):
                result.append(candidate)
        return tuple(result)
