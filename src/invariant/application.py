"""Transaction-oriented protocol application shared by CLI and MCP."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from pathlib import Path
from typing import Any, Mapping, Sequence

from invariant.errors import Blocked, InvariantError
from invariant.gateway import CapabilityService
from invariant.governance import GovernanceStore, compile_obligations, select
from invariant.ledger import Ledger, LedgerStore
from invariant.lifecycle.actions import ActionService
from invariant.lifecycle.changes import ChangeService
from invariant.mechanics import config, git
from invariant.mechanics.landing import (
    IntegrationService,
    PublicationService,
    governed_worktree_changes,
    validate_governance_history,
    validate_landing_attestation,
)
from invariant.mechanics.verification import VerificationService
from invariant.mechanics.work import CandidateService, WorkService
from invariant.planning import RecommendationService
from invariant.protocol import CapabilityName, Outcome, PROTOCOL_VERSION, Scope
from invariant.repository import Repository


@dataclass(frozen=True)
class OperationResult:
    outcome: Outcome
    result: Mapping[str, Any]

    def envelope(self, command: str) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "command": command,
            "status": "ok",
            "outcome": self.outcome.value,
            "result": dict(self.result),
            "diagnostics": [],
        }


class InvariantApplication:
    def __init__(
        self,
        repository: Repository,
        *,
        planner=None,
        principal: str = "user:local",
    ) -> None:
        self.repository = repository
        self.store = LedgerStore(repository, principal=principal)
        self.capabilities = CapabilityService(self.store)
        self.changes = ChangeService(
            self.store, self.capabilities, RecommendationService(planner)
        )
        self.actions = ActionService(self.store, self.capabilities)
        self.work = WorkService(self.store, self.capabilities)
        self.candidates = CandidateService(self.store, self.capabilities)
        self.verification = VerificationService(self.store, self.capabilities)
        self.integration = IntegrationService(self.store, self.capabilities)
        self.publication = PublicationService(self.store, self.capabilities)

    @classmethod
    def bind(
        cls,
        path: Path | str = ".",
        *,
        planner=None,
        principal: str = "user:local",
    ) -> "InvariantApplication":
        return cls(Repository.bind(path), planner=planner, principal=principal)

    @staticmethod
    def initialize(path: Path | str = ".", **values: Any) -> OperationResult:
        repo = git.root(path)
        git.require_capabilities(repo)
        nested = git.tracked_nested_invariant_paths(repo)
        if nested:
            raise InvariantError(
                "Invariant: repository contains nested Invariant state",
                code="nested_invariant",
                data={"paths": nested},
            )
        policy_path = repo / config.CONFIG_PATH
        if policy_path.exists():
            raise InvariantError(
                f"Invariant: {config.CONFIG_PATH.as_posix()} already exists",
                code="config_exists",
            )
        if not git.tracked_worktree_clean(repo):
            raise Blocked(
                "Invariant: initialization requires a clean tracked worktree",
                code="dirty_initialization",
                data={"paths": git.changed_paths(repo)},
                lines=[
                    "STATUS: tracked changes are not included in initialization",
                    "NEXT: commit or stash them, then run invariant init again",
                ],
            )
        if git.resolve(repo, "HEAD") is None:
            nonce = git.common_dir(repo) / "invariant-bootstrap"
            if not nonce.exists():
                nonce.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        lines = config.initialize(repo, **values)
        git.run(["add", "--", config.CONFIG_PATH.as_posix()], cwd=repo)
        git.run(
            ["commit", "-q", "-m", "Initialize Invariant", "--", config.CONFIG_PATH.as_posix()],
            cwd=repo,
        )
        commit = git.resolve(repo, "HEAD")
        return OperationResult(
            Outcome.COMPLETED,
            {
                "policy": config.lines(config.resolve(repo)),
                "messages": [*lines, f"COMMIT: {commit}"],
                "commit": commit,
            },
        )

    def state_validate(self) -> OperationResult:
        dirty_governance = governed_worktree_changes(self.repository.primary_worktree)
        if dirty_governance:
            raise InvariantError(
                "Invariant: mutable worktree governance is not accepted state",
                code="invalid_state",
                data={"paths": dirty_governance},
            )
        target, target_head, policy = self.repository.integration()
        governance = GovernanceStore(self.repository.primary_worktree).load(target_head)
        changes: list[dict[str, str]] = []
        states: dict[str, Mapping[str, Any]] = {}
        refs = git.run(
            ["for-each-ref", "--format=%(refname)", "refs/invariant/changes"],
            cwd=self.repository.root,
            check=False,
        ).stdout.splitlines()
        for ref in refs:
            change_id = ref.removeprefix("refs/invariant/changes/")
            ledger = self.store.load(change_id)
            states[change_id] = ledger.state
            if ledger.state.get("stage") == "completed":
                validate_landing_attestation(self.repository.root, ledger.state)
            changes.append(
                {"id": change_id, "ledger": ledger.head, "stage": str(ledger.state["stage"])}
            )
        validate_governance_history(self.repository.root, target_head, states)
        return OperationResult(
            Outcome.COMPLETED,
            {
                "valid": True,
                "repository": self.repository.identity,
                "policy": {
                    "authority": {
                        "intent": {"suppliers": list(policy.authority.intent.suppliers)},
                        "resolution": {
                            "delegation": policy.authority.resolution.delegation
                        },
                    },
                    "execution": {"transitions": policy.execution.transitions},
                    "integration_branch": target,
                    "publication": policy.publication,
                    "parallelism": {"maximum": policy.parallelism.maximum},
                },
                "governance": {
                    "records": len(governance.records),
                    "digest": governance.digest,
                },
                "changes": changes,
            },
        )

    def governance_context(
        self,
        *,
        paths: Sequence[str] = (),
        interfaces: Sequence[str] = (),
        domains: Sequence[str] = (),
        contracts: Sequence[str] = (),
        capability: str | None = None,
        at: str | None = None,
    ) -> OperationResult:
        scope = Scope.create(
            paths=paths, interfaces=interfaces, domains=domains, contracts=contracts
        )
        try:
            selected_capability = CapabilityName(capability) if capability else None
        except ValueError as exc:
            raise InvariantError(
                f"Invariant: unknown capability '{capability}'",
                code="unknown_capability",
            ) from exc
        target, target_head, policy = self.repository.integration()
        ground = at or target_head
        governance = GovernanceStore(self.repository.primary_worktree).load(ground)
        selection = select(governance, scope, selected_capability)
        obligations = compile_obligations(
            self.repository.policy_at(ground, target) if at else policy,
            selection,
            scope,
        )
        return OperationResult(
            Outcome.COMPLETED,
            {
                "selection": selection.as_dict(),
                "obligations": obligations.as_dict(),
            },
        )

    def change_open(
        self,
        change_id: str,
        *,
        intent: str,
        supplier: str,
        paths: Sequence[str] = (),
        interfaces: Sequence[str] = (),
        domains: Sequence[str] = (),
        contracts: Sequence[str] = (),
        operation_id: str,
    ) -> OperationResult:
        ledger = self.changes.open(
            change_id,
            statement=intent,
            supplier=supplier,
            scope=Scope.create(
                paths=paths,
                interfaces=interfaces,
                domains=domains,
                contracts=contracts,
            ),
            operation_id=operation_id,
        )
        return self._ledger_result(ledger, Outcome.READY)

    def change_recommend(
        self, change_id: str, *, operation_id: str, host_capacity: int | None = None
    ) -> OperationResult:
        return self._ledger_result(
            self.changes.recommend(
                change_id,
                operation_id=operation_id,
                host_capacity=host_capacity,
            ),
            Outcome.READY,
        )

    def change_inspect(self, change_id: str) -> OperationResult:
        return OperationResult(
            Outcome.COMPLETED, {"change": self.changes.inspect(change_id)}
        )

    def change_handoff(self, change_id: str) -> OperationResult:
        return OperationResult(
            Outcome.COMPLETED, {"handoff": self.changes.handoff(change_id)}
        )

    def change_resume(
        self, capsule: Mapping[str, Any], *, actor: str, operation_id: str
    ) -> OperationResult:
        return self._ledger_result(
            self.changes.resume(capsule, actor=actor, operation_id=operation_id),
            Outcome.READY,
        )

    def action_inspect(self, change_id: str, action_id: str) -> OperationResult:
        return OperationResult(
            Outcome.COMPLETED, self.actions.inspect(change_id, action_id)
        )

    def action_respond(
        self,
        change_id: str,
        action_id: str,
        *,
        response: Mapping[str, Any],
        actor: str,
        operation_id: str,
        token: str | None = None,
    ) -> OperationResult:
        return self._ledger_result(
            self.actions.respond(
                change_id,
                action_id,
                response=response,
                actor=actor,
                operation_id=operation_id,
                token=token,
            ),
            Outcome.READY,
        )

    def capability_request(self, change_id: str, **values: Any) -> OperationResult:
        result = self.capabilities.request(change_id, **values)
        return OperationResult(result.outcome, result.as_dict())

    def capability_inspect(self, change_id: str, identifier: str) -> OperationResult:
        return OperationResult(
            Outcome.COMPLETED, self.capabilities.inspect(change_id, identifier)
        )

    def capability_revoke(
        self,
        change_id: str,
        grant_id: str,
        *,
        actor: str,
        operation_id: str,
        reason: str,
    ) -> OperationResult:
        return self._ledger_result(
            self.capabilities.revoke(
                change_id,
                grant_id,
                actor=actor,
                operation_id=operation_id,
                reason=reason,
            ),
            Outcome.COMPLETED,
        )

    def work_create(self, change_id: str, **values: Any) -> OperationResult:
        result = self.work.create(change_id, **values)
        return OperationResult(
            Outcome.READY,
            {"ledger": result.ledger.head, "attempt": dict(result.attempt)},
        )

    def work_submit(self, change_id: str, **values: Any) -> OperationResult:
        result = self.work.submit(change_id, **values)
        return OperationResult(
            Outcome.READY,
            {"ledger": result.ledger.head, "attempt": dict(result.attempt)},
        )

    def work_discard(self, change_id: str, **values: Any) -> OperationResult:
        return self._ledger_result(
            self.work.discard(change_id, **values), Outcome.COMPLETED
        )

    def candidate_converge(self, change_id: str, **values: Any) -> OperationResult:
        return self._ledger_result(
            self.candidates.converge(change_id, **values), Outcome.READY
        )

    def candidate_evidence(
        self,
        change_id: str,
        *,
        tokens: Mapping[str, str],
        operation_id: str,
    ) -> OperationResult:
        ledger = self.verification.capture(
            change_id, tokens=tokens, operation_id=operation_id
        )
        outcome = (
            Outcome.NEEDS_INPUT
            if ledger.state["stage"] == "awaiting-action"
            else Outcome.READY
        )
        return self._ledger_result(ledger, outcome)

    def integration_land(self, change_id: str, **values: Any) -> OperationResult:
        return self._ledger_result(
            self.integration.land(change_id, **values), Outcome.COMPLETED
        )

    def integration_reconcile(
        self, change_id: str, *, operation_id: str
    ) -> OperationResult:
        return self._ledger_result(
            self.integration.reconcile(change_id, operation_id=operation_id),
            Outcome.COMPLETED,
        )

    def publication_publish(self, change_id: str, **values: Any) -> OperationResult:
        return self._ledger_result(
            self.publication.publish(change_id, **values), Outcome.COMPLETED
        )

    def change_invalidate(self, change_id: str, **values: Any) -> OperationResult:
        return self._ledger_result(
            self.changes.invalidate(change_id, **values), Outcome.COMPLETED
        )

    @staticmethod
    def _ledger_result(ledger: Ledger, outcome: Outcome) -> OperationResult:
        return OperationResult(
            outcome,
            {
                "change": ledger.change_id,
                "ledger": ledger.head,
                "stage": ledger.state["stage"],
            },
        )
