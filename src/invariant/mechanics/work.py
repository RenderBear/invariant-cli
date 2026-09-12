from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError
from invariant.gateway import CapabilityService
from invariant.ledger import Ledger, LedgerStore
from invariant.mechanics import git
from invariant.mechanics.locks import file_lock
from invariant.protocol import CapabilityName, EventKind, canonical_json, require_id


@dataclass(frozen=True)
class WorkResult:
    ledger: Ledger
    attempt: Mapping[str, Any]


def _claim_allows(claim: str, path: str) -> bool:
    if not claim.startswith("repo:"):
        return False
    prefix = claim.removeprefix("repo:").strip("/")
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


class WorkService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities

    def create(
        self,
        change_id: str,
        *,
        unit_id: str,
        attempt_id: str,
        actor: str,
        token: str,
        operation_id: str,
    ) -> WorkResult:
        require_id(unit_id, "unit id")
        require_id(attempt_id, "attempt id")
        existing_ledger = self.store.load(change_id)
        replay = existing_ledger.event_for(f"{operation_id}.attempt")
        if replay:
            attempt = existing_ledger.state.get("attempts", {}).get(attempt_id)
            if (
                replay.kind is EventKind.ATTEMPT_CREATED
                and replay.payload.get("attempt", {}).get("id") == attempt_id
                and attempt
            ):
                return WorkResult(existing_ledger, attempt)
            raise InvariantError(
                "Invariant: operation id was reused with different work input",
                code="invalid_invocation",
            )
        resource = f"{unit_id}/{attempt_id}"
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.WORKTREE_CREATE,
            resource=resource,
            operation_id=operation_id,
        )
        recommendation = use.ledger.state.get("recommendation") or {}
        unit = next((item for item in recommendation.get("units", []) if item["id"] == unit_id), None)
        if not unit:
            raise InvariantError(f"Invariant: unknown unit '{unit_id}'", code="invalid_invocation")
        existing = use.ledger.state.get("attempts", {}).get(attempt_id)
        if existing:
            return WorkResult(use.ledger, existing)
        base = use.ledger.state.get("candidate", {}).get("commit") if unit.get("depends_on") else None
        base = base or use.ledger.state["base"]
        work_ref = f"refs/invariant/work/{change_id}/{unit_id}/{attempt_id}"
        runtime = self.repository.primary_worktree / ".invariant/runtime/worktrees"
        worktree = runtime / f"{change_id}-{unit_id}-{attempt_id}"
        lock = self.repository.common_dir / "invariant-locks" / f"work-{change_id}-{unit_id}.lock"
        with file_lock(lock):
            ref_tip = git.resolve(self.repository.root, work_ref)
            if ref_tip and ref_tip != base:
                raise Blocked("Invariant: work ref already has different content", code="concurrent_ref_movement")
            if not ref_tip and not git.update_ref(self.repository.root, work_ref, base, None):
                raise Blocked("Invariant: work ref was created concurrently", code="concurrent_ref_movement")
            if not worktree.exists():
                runtime.mkdir(parents=True, exist_ok=True)
                result = git.run(
                    ["worktree", "add", "--quiet", "--detach", str(worktree), work_ref],
                    cwd=self.repository.root,
                    check=False,
                )
                if result.returncode:
                    raise InvariantError(
                        f"Invariant: {result.stderr or result.stdout}", code="missing_worktree"
                    )
                git.run(["symbolic-ref", "HEAD", work_ref], cwd=worktree)
            consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
            attempt = {
                "id": attempt_id,
                "unit": unit_id,
                "actor": actor,
                "base": base,
                "ref": work_ref,
                "worktree": str(worktree),
                "claims": unit["claims"],
                "status": "active",
            }
            ledger = self.store.append(
                change_id,
                operation_id=f"{operation_id}.attempt",
                kind=EventKind.ATTEMPT_CREATED,
                actor="kernel:repository/worktree",
                payload={"attempt": attempt},
                expected_head=consumed.head,
                anchors=[base],
            )
            return WorkResult(ledger, ledger.state["attempts"][attempt_id])

    def submit(
        self,
        change_id: str,
        *,
        attempt_id: str,
        actor: str,
        operation_id: str,
    ) -> WorkResult:
        ledger = self.store.load(change_id)
        replay = ledger.event_for(operation_id)
        if replay:
            attempt = ledger.state.get("attempts", {}).get(attempt_id)
            if (
                replay.kind is EventKind.ATTEMPT_SUBMITTED
                and replay.payload.get("attempt") == attempt_id
                and attempt
            ):
                return WorkResult(ledger, attempt)
            raise InvariantError(
                "Invariant: operation id was reused with different submission input",
                code="invalid_invocation",
            )
        attempt = ledger.state.get("attempts", {}).get(attempt_id)
        if not attempt:
            raise InvariantError(f"Invariant: unknown attempt '{attempt_id}'", code="invalid_invocation")
        write_grant = next(
            (
                grant
                for grant in ledger.state.get("grants", {}).values()
                if grant.get("capability") == CapabilityName.WORKTREE_WRITE.value
                and grant.get("attempt") == attempt_id
                and grant.get("status") == "live"
            ),
            None,
        )
        if not write_grant:
            raise InvariantError(
                "Invariant: a live worktree.write grant is required for submission",
                code="capability_required",
            )
        path = Path(attempt["worktree"])
        if not path.is_dir():
            raise Blocked("Invariant: attempt worktree is missing", code="missing_worktree")
        if not git.worktree_clean(path):
            raise Blocked("Invariant: attempt worktree must be clean and committed", code="dirty_worktree")
        tip = git.resolve(self.repository.root, attempt["ref"])
        if not tip:
            raise Blocked("Invariant: attempt ref is missing", code="missing_object")
        paths = git.changed_paths(self.repository.root, attempt["base"], tip)
        outside = [
            changed for changed in paths
            if not any(_claim_allows(claim, changed) for claim in attempt["claims"])
        ]
        if outside:
            rejected = self.store.append(
                change_id,
                operation_id=operation_id,
                kind=EventKind.ATTEMPT_REJECTED,
                actor="kernel:repository/worktree",
                payload={
                    "attempt": attempt_id,
                    "reason": "parallel_claim_violation",
                    "paths": outside,
                },
                expected_head=ledger.head,
                anchors=[tip],
            )
            raise Blocked(
                "Invariant: attempt changed paths outside its claims; work is retained",
                code="parallel_claim_violation",
                data={"paths": outside, "ledger": rejected.head},
            )
        result = {"tip": tip, "tree": git.tree_of(self.repository.root, tip), "paths": paths}
        narrowed = self.capabilities.revoke(
            change_id,
            write_grant["id"],
            actor="kernel:repository/worktree",
            operation_id=f"{operation_id}.close-write",
            reason="attempt submitted",
        )
        updated = self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.ATTEMPT_SUBMITTED,
            actor=actor,
            payload={"attempt": attempt_id, "result": result},
            expected_head=narrowed.head,
            anchors=[tip],
        )
        return WorkResult(updated, updated.state["attempts"][attempt_id])

    def restore(self, change_id: str, attempt_id: str) -> WorkResult:
        ledger = self.store.load(change_id)
        attempt = ledger.state.get("attempts", {}).get(attempt_id)
        if not attempt:
            raise InvariantError(f"Invariant: unknown attempt '{attempt_id}'", code="invalid_invocation")
        worktree = Path(attempt["worktree"])
        if not worktree.exists():
            worktree.parent.mkdir(parents=True, exist_ok=True)
            git.run(["worktree", "prune"], cwd=self.repository.root, check=False)
            git.run(["worktree", "add", "--quiet", "--detach", str(worktree), attempt["ref"]], cwd=self.repository.root)
            git.run(["symbolic-ref", "HEAD", attempt["ref"]], cwd=worktree)
        return WorkResult(ledger, attempt)

    def discard(
        self,
        change_id: str,
        *,
        refs: list[str],
        token: str,
        operation_id: str,
    ) -> Ledger:
        targets = sorted(set(refs))
        if not targets:
            raise InvariantError("Invariant: discard requires exact refs", code="invalid_invocation")
        existing_ledger = self.store.load(change_id)
        replay = existing_ledger.event_for(operation_id)
        if replay:
            if replay.kind is EventKind.WORK_DISCARDED and replay.payload.get("refs") == targets:
                return existing_ledger
            raise InvariantError(
                "Invariant: operation id was reused with different discard input",
                code="invalid_invocation",
            )
        work_prefix = f"refs/invariant/work/{change_id}/"
        candidate_ref = f"refs/invariant/candidates/{change_id}"
        if any(
            not (ref.startswith(work_prefix) or ref == candidate_ref)
            for ref in targets
        ):
            raise InvariantError("Invariant: discard target escapes this change", code="invalid_invocation")
        resource = canonical_json(targets)
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.WORK_DISCARD,
            resource=resource,
            operation_id=operation_id,
        )
        resolved = {ref: git.resolve(self.repository.root, ref) for ref in targets}
        if any(value is None for value in resolved.values()):
            raise Blocked("Invariant: a discard ref is stale", code="stale_grant")
        consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
        for attempt in use.ledger.state.get("attempts", {}).values():
            if attempt.get("ref") in targets:
                path = Path(attempt["worktree"])
                if path.exists():
                    git.run(["worktree", "remove", "--force", str(path)], cwd=self.repository.root)
        for ref, oid in resolved.items():
            assert oid is not None
            if not git.delete_ref(self.repository.root, ref, oid):
                raise Blocked("Invariant: discard ref moved", code="concurrent_ref_movement")
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.WORK_DISCARDED,
            actor="kernel:repository/worktree",
            payload={"refs": targets, "objects": resolved},
            expected_head=consumed.head,
        )


class CandidateService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities

    def converge(
        self,
        change_id: str,
        *,
        attempt_id: str,
        token: str,
        operation_id: str,
    ) -> Ledger:
        existing_ledger = self.store.load(change_id)
        completed_replay = existing_ledger.event_for(f"{operation_id}.candidate")
        if completed_replay:
            if completed_replay.kind is EventKind.CANDIDATE_CONSTRUCTED:
                return existing_ledger
            raise InvariantError(
                "Invariant: operation id was reused with different convergence input",
                code="invalid_invocation",
            )
        partial_replay = existing_ledger.event_for(f"{operation_id}.unit")
        if partial_replay:
            if (
                partial_replay.kind is not EventKind.UNIT_CONVERGED
                or partial_replay.payload.get("attempt") != attempt_id
            ):
                raise InvariantError(
                    "Invariant: operation id was reused with different convergence input",
                    code="invalid_invocation",
                )
            candidate_ref = f"refs/invariant/candidates/{change_id}"
            combined = git.resolve(self.repository.root, candidate_ref)
            if not combined:
                raise Blocked(
                    "Invariant: interrupted candidate convergence lost its durable ref",
                    code="missing_object",
                )
            value = {
                "ref": candidate_ref,
                "commit": combined,
                "tree": git.tree_of(self.repository.root, combined),
                "base": existing_ledger.state["base"],
                "paths": git.changed_paths(
                    self.repository.root, existing_ledger.state["base"], combined
                ),
                "units": sorted(set(existing_ledger.state["converged"])),
            }
            return self.store.append(
                change_id,
                operation_id=f"{operation_id}.candidate",
                kind=EventKind.CANDIDATE_CONSTRUCTED,
                actor="kernel:repository/candidate",
                payload={"candidate": value},
                expected_head=existing_ledger.head,
                anchors=[combined],
            )
        resource = attempt_id
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.CANDIDATE_CONVERGE,
            resource=resource,
            operation_id=operation_id,
        )
        attempt = use.ledger.state["attempts"][attempt_id]
        candidate = use.ledger.state.get("candidate")
        current = candidate["commit"] if candidate else use.ledger.state["base"]
        tip = attempt["tip"]
        if git.is_ancestor(self.repository.root, current, tip):
            combined = tip
        else:
            tree = git.merge_tree(self.repository.root, current, tip)
            combined = git.commit_tree(
                self.repository.root,
                tree,
                f"Invariant candidate: {change_id} + {attempt['unit']}\n",
                parents=[current, tip],
            )
        candidate_ref = f"refs/invariant/candidates/{change_id}"
        observed = git.resolve(self.repository.root, candidate_ref)
        expected = candidate["commit"] if candidate else None
        if observed != expected:
            raise Blocked("Invariant: candidate advanced concurrently", code="concurrent_ref_movement")
        if observed != combined and not git.update_ref(self.repository.root, candidate_ref, combined, expected):
            raise Blocked("Invariant: candidate advanced concurrently", code="concurrent_ref_movement")
        consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
        converged = self.store.append(
            change_id,
            operation_id=f"{operation_id}.unit",
            kind=EventKind.UNIT_CONVERGED,
            actor="kernel:repository/candidate",
            payload={"unit": attempt["unit"], "attempt": attempt_id, "commit": tip},
            expected_head=consumed.head,
            anchors=[tip],
        )
        units = sorted(set(converged.state["converged"]))
        value = {
            "ref": candidate_ref,
            "commit": combined,
            "tree": git.tree_of(self.repository.root, combined),
            "base": use.ledger.state["base"],
            "paths": git.changed_paths(
                self.repository.root, use.ledger.state["base"], combined
            ),
            "units": units,
        }
        return self.store.append(
            change_id,
            operation_id=f"{operation_id}.candidate",
            kind=EventKind.CANDIDATE_CONSTRUCTED,
            actor="kernel:repository/candidate",
            payload={"candidate": value},
            expected_head=converged.head,
            anchors=[combined],
        )
