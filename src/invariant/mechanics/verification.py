from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.gateway import CapabilityService
from invariant.governance import GovernanceStore, compile_obligations, select
from invariant.ledger import Ledger, LedgerStore
from invariant.mechanics import config, git
from invariant.protocol import ActionKind, CapabilityName, EventKind, Scope, digest


class VerificationService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities

    def capture(
        self,
        change_id: str,
        *,
        tokens: Mapping[str, str],
        operation_id: str,
    ) -> Ledger:
        ledger = self.store.load(change_id)
        replay = ledger.event_for(operation_id)
        if replay:
            if replay.kind is EventKind.CANDIDATE_EVIDENCED:
                return ledger
            raise InvariantError(
                "Invariant: operation id was reused with different evidence input",
                code="invalid_invocation",
            )
        candidate = ledger.state.get("candidate")
        if not candidate:
            raise InvariantError("Invariant: no exact candidate exists", code="missing_object")
        scope_raw = ledger.state["scope"]
        scope = Scope.create(
            paths=(*scope_raw.get("paths", []), *candidate.get("paths", [])),
            interfaces=scope_raw.get("interfaces", []),
            domains=scope_raw.get("domains", []), contracts=scope_raw.get("contracts", []),
        )
        governance = GovernanceStore(self.repository.primary_worktree).load(ledger.state["base"])
        candidate_governance = GovernanceStore(
            self.repository.primary_worktree
        ).load(candidate["commit"])
        config.resolve_at(
            self.repository.primary_worktree,
            candidate["commit"],
            ledger.state["target"]["branch"],
        )
        selection = select(governance, scope, CapabilityName.INTEGRATION_LAND)
        policy = self.repository.policy_at(
            ledger.state["base"], ledger.state["target"]["branch"]
        )
        obligations = compile_obligations(policy, selection, scope)
        required = set(obligations.required_verifiers)
        recommendation = ledger.state.get("recommendation") or {}
        for unit in recommendation.get("units", []):
            required.update(unit.get("checks", []))
        if set(tokens) != required:
            missing = sorted(required - set(tokens))
            extra = sorted(set(tokens) - required)
            raise InvariantError(
                "Invariant: verifier grants must exactly match the compiled set",
                code="missing_evidence",
                data={"missing": missing, "extra": extra},
            )
        uses = {
            locator: self.capabilities.use(
                change_id,
                token=token,
                capability=CapabilityName.VERIFICATION_RUN,
                resource=locator,
                operation_id=f"{operation_id}.{index}",
            )
            for index, (locator, token) in enumerate(sorted(tokens.items()))
        }
        temporary = Path(tempfile.mkdtemp(prefix="invariant-verify-"))
        checkout = temporary / "tree"
        evidence: list[dict[str, Any]] = []
        try:
            git.run(["worktree", "add", "--quiet", "--detach", str(checkout), candidate["commit"]], cwd=self.repository.root)
            snapshot = {
                "kind": "candidate-snapshot",
                "candidate": candidate["tree"],
                "base": candidate["base"],
                "paths": git.changed_paths(self.repository.root, candidate["base"], candidate["commit"]),
                "candidate_governance": candidate_governance.digest,
            }
            snapshot["id"] = "evidence-" + digest(snapshot)
            evidence.append(snapshot)
            current = ledger
            for index, locator in enumerate(sorted(required)):
                current = self.capabilities.consume(
                    uses[locator], operation_id=f"{operation_id}.consume{index}"
                )
                result = self._run(checkout, locator)
                observation = {
                    "kind": "verifier",
                    "locator": locator,
                    "candidate": candidate["tree"],
                    "status": "passed" if result.returncode == 0 else "failed",
                    "exit_status": result.returncode,
                    "output_digest": sha256((result.stdout + result.stderr).encode("utf-8")).hexdigest(),
                    "environment": {"python": sys.version.split()[0], "platform": sys.platform},
                }
                observation["id"] = "evidence-" + digest(observation)
                evidence.append(observation)
                if result.returncode:
                    failed = self.store.append(
                        change_id,
                        operation_id=f"{operation_id}.failed{index}",
                        kind=EventKind.CANDIDATE_EVIDENCED,
                        actor="kernel:repository/verification",
                        payload={
                            "candidate": candidate["tree"],
                            "evidence": evidence,
                            "evidence_digest": digest(evidence),
                            "governance": selection.as_dict(),
                            "obligations": obligations.as_dict(),
                            "next_stage": "evidencing",
                        },
                        expected_head=current.head,
                        anchors=[candidate["commit"]],
                    )
                    raise Blocked(
                        f"Invariant: verifier '{locator}' failed",
                        code="verification_failed",
                        data={"evidence": observation, "ledger": failed.head},
                    )
                # Later uses were loaded at the same prior head. Refresh their causal ledger;
                # candidate-bound fields remain identical and token identity remains live.
                for later in sorted(required)[index + 1 :]:
                    uses[later] = self.capabilities.use(
                        change_id,
                        token=tokens[later],
                        capability=CapabilityName.VERIFICATION_RUN,
                        resource=later,
                        operation_id=f"{operation_id}.refresh{index}",
                    )
            next_stage = "awaiting-action" if obligations.required_reviews else "ready-to-land"
            evidenced = self.store.append(
                change_id,
                operation_id=operation_id,
                kind=EventKind.CANDIDATE_EVIDENCED,
                actor="kernel:repository/verification",
                payload={
                    "candidate": candidate["tree"],
                    "evidence": evidence,
                    "evidence_digest": digest(evidence),
                    "governance": selection.as_dict(),
                    "obligations": obligations.as_dict(),
                    "next_stage": next_stage,
                },
                expected_head=current.head,
                anchors=[candidate["commit"]],
            )
            if obligations.required_reviews:
                mode = obligations.required_reviews[0]
                action_id = f"review-{candidate['tree'][:16]}"
                action = {
                    "id": action_id,
                    "kind": (
                        ActionKind.REVIEW_INDEPENDENT.value
                        if mode == "independent" else ActionKind.REVIEW_SEMANTICS.value
                    ),
                    "schema": f"invariant://v1/actions/review-{mode}",
                    "blocking": True,
                    "for_capability": CapabilityName.INTEGRATION_LAND.value,
                    "bindings": {
                        "change": change_id,
                        "ledger": evidenced.head,
                        "intent": evidenced.state["intent"]["digest"],
                        "supplier": evidenced.state["intent"]["supplier"],
                        "recommendation": evidenced.state["recommendation"]["digest"],
                        "candidate": candidate["tree"],
                        "governance": selection.digest,
                        "evidence": digest(evidence),
                    },
                    "context": {
                        "intent": evidenced.state["intent"],
                        "governance": selection.as_dict(),
                        "evidence": evidence,
                    },
                }
                return self.store.append(
                    change_id,
                    operation_id=f"{operation_id}.action",
                    kind=EventKind.ACTION_OPENED,
                    actor="kernel:repository/semantic",
                    payload={"action": action},
                    expected_head=evidenced.head,
                )
            return evidenced
        finally:
            git.run(["worktree", "remove", "--force", str(checkout)], cwd=self.repository.root, check=False)
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _run(checkout: Path, locator: str) -> subprocess.CompletedProcess[str]:
        kind, separator, value = locator.partition(":")
        if not separator or Path(value).is_absolute() or ".." in Path(value).parts:
            raise InvariantError(f"Invariant: invalid verifier '{locator}'", code="invalid_state")
        target = checkout / value
        if not target.is_file():
            raise InvariantError(f"Invariant: verifier '{locator}' does not resolve", code="unresolved_locator")
        if kind == "test":
            command = [sys.executable, "-m", "pytest", value]
        elif kind == "command":
            command = [str(target)]
        else:
            raise InvariantError(f"Invariant: unsupported verifier '{locator}'", code="invalid_state")
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(command, cwd=checkout, capture_output=True, text=True, check=False, env=environment)
