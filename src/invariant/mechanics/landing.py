"""Exact candidate landing and separately bounded publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.gateway import CapabilityService
from invariant.ledger import Ledger, LedgerStore
from invariant.mechanics import git
from invariant.mechanics.locks import file_lock
from invariant.protocol import CapabilityName, EventKind, PROTOCOL_VERSION, digest


@dataclass(frozen=True)
class PushTarget:
    remote: str
    merge_ref: str

    @property
    def label(self) -> str:
        return f"{self.remote}/{self.merge_ref.removeprefix('refs/heads/')}"


class IntegrationService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities

    def land(
        self,
        change_id: str,
        *,
        token: str,
        operation_id: str,
        subject: str | None = None,
    ) -> Ledger:
        existing = self.store.load(change_id)
        replay = existing.event_for(operation_id)
        if replay:
            if replay.kind is EventKind.LANDING_COMPLETED:
                return existing
            raise InvariantError(
                "Invariant: operation id was reused with different landing input",
                code="invalid_invocation",
            )
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.INTEGRATION_LAND,
            resource=(self.store.load(change_id).state.get("candidate") or {}).get("tree", ""),
            operation_id=operation_id,
        )
        state = use.ledger.state
        candidate = state["candidate"]
        target = state["target"]
        current = git.resolve(self.repository.root, target["ref"])
        if current != state["base"]:
            raise Blocked(
                "Invariant: integration target moved; candidate must be recomputed",
                code="concurrent_ref_movement",
                data={"expected": state["base"], "actual": current},
            )
        checkout = git.worktree_for_branch(self.repository.root, target["branch"])
        self._preflight(checkout, state["base"], candidate["commit"])
        message = self._message(state, subject, str(use.grant["decision_digest"]))
        landing_commit = git.commit_tree(
            self.repository.root,
            candidate["tree"],
            message,
            parents=[state["base"]],
        )
        lock = self.repository.common_dir / "invariant-locks" / f"land-{target['branch'].replace('/', '%')}.lock"
        with file_lock(lock):
            if git.resolve(self.repository.root, target["ref"]) != state["base"]:
                raise Blocked("Invariant: integration target moved", code="concurrent_ref_movement")
            consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
            transaction = {
                "status": "started",
                "candidate": candidate["tree"],
                "commit": landing_commit,
                "target": target,
                "previous": state["base"],
            }
            started = self.store.append(
                change_id,
                operation_id=f"{operation_id}.start",
                kind=EventKind.LANDING_STARTED,
                actor="kernel:repository/landing",
                payload={"landing": transaction},
                expected_head=consumed.head,
                anchors=[landing_commit],
            )
            if not git.update_ref(self.repository.root, target["ref"], landing_commit, state["base"]):
                return self.store.append(
                    change_id,
                    operation_id=f"{operation_id}.failed",
                    kind=EventKind.LANDING_RECONCILED,
                    actor="kernel:repository/landing",
                    payload={"landing": {**transaction, "status": "not-moved"}, "completed": False},
                    expected_head=started.head,
                )
            if checkout:
                git.run(["reset", "--hard", "--quiet", landing_commit], cwd=checkout)
            return self.store.append(
                change_id,
                operation_id=operation_id,
                kind=EventKind.LANDING_COMPLETED,
                actor="kernel:repository/landing",
                payload={"landing": {**transaction, "status": "completed"}},
                expected_head=started.head,
                anchors=[landing_commit],
            )

    def reconcile(self, change_id: str, *, operation_id: str) -> Ledger:
        ledger = self.store.load(change_id)
        landing = ledger.state.get("landing")
        if not landing or landing.get("status") != "started":
            return ledger
        current = git.resolve(self.repository.root, landing["target"]["ref"])
        if current == landing["commit"]:
            status, completed = "completed", True
        elif current == landing["previous"]:
            status, completed = "not-moved", False
        else:
            raise Blocked(
                "Invariant: interrupted landing target has an unexpected value",
                code="concurrent_ref_movement",
                data={"expected": [landing["previous"], landing["commit"]], "actual": current},
            )
        return self.store.append(
            change_id,
            operation_id=operation_id,
            kind=EventKind.LANDING_RECONCILED,
            actor="kernel:repository/landing",
            payload={"landing": {**landing, "status": status}, "completed": completed},
            expected_head=ledger.head,
            anchors=[landing["commit"]],
        )

    def _preflight(self, checkout: Path | None, base: str, candidate: str) -> None:
        if not checkout:
            return
        if not git.tracked_worktree_clean(checkout):
            raise Blocked(
                "Invariant: integration checkout has tracked edits",
                code="dirty_integration_checkout",
            )
        untracked = set(
            git.run(["ls-files", "--others", "--exclude-standard"], cwd=checkout).stdout.splitlines()
        )
        changed = set(git.changed_paths(self.repository.root, base, candidate))
        collisions = sorted(untracked & changed)
        if collisions:
            raise Blocked(
                "Invariant: candidate would overwrite untracked integration files",
                code="untracked_collision",
                data={"paths": collisions},
            )

    @staticmethod
    def _message(state: dict[str, Any], subject: str | None, landing_decision: str) -> str:
        line = (subject or state["intent"]["statement"].splitlines()[0]).strip()
        if not line or "\n" in line or "\r" in line:
            raise InvariantError("Invariant: landing subject must be one line", code="invalid_invocation")
        recommendation = state["recommendation"]
        trailers = [
            f"Invariant-Protocol: {PROTOCOL_VERSION}",
            f"Invariant-Change: {state['change']}",
            f"Invariant-Intent: {state['intent']['digest']} {state['intent']['supplier']}",
            f"Invariant-Plan: {recommendation['id']}@{recommendation['digest']}",
        ]
        for unit in recommendation["units"]:
            attempts = [item for item in state["attempts"].values() if item["unit"] == unit["id"] and item.get("tip")]
            if attempts:
                attempt = attempts[-1]
                trailers.append(f"Invariant-Unit: {unit['id']} {attempt['tree']} {attempt['actor']}")
        for grant in state["grants"].values():
            if grant.get("status") == "consumed":
                trailers.append(f"Invariant-Decision: {grant['decision_digest']}")
        trailers.append(f"Invariant-Decision: {landing_decision}")
        for record in state["governance"]["records"]:
            trailers.append(f"Invariant-Governance: {record}")
        evidence_digest = digest(state.get("evidence", []))
        trailers.append(f"Invariant-Evidence: {evidence_digest}")
        for review in state.get("reviews", []):
            trailers.append(f"Invariant-Review: {review['digest']} {review['mode']} {review['authority']}")
        trailers.append(f"Invariant-Landing-Parent: {state['base']}")
        return line + "\n\n" + "\n".join(trailers) + "\n"


def validate_landing_attestation(repo: Path, state: Mapping[str, Any]) -> None:
    """Validate the portable bindings on one completed landing commit."""

    landing = state.get("landing") or {}
    candidate = state.get("candidate") or {}
    commit = landing.get("commit")
    if not isinstance(commit, str) or not commit:
        raise InvariantError("Invariant: completed change lacks a landing commit", code="invalid_attestation")

    failures: list[str] = []
    parents = git.run(["rev-list", "--parents", "-n", "1", commit], cwd=repo, check=False)
    parent_values = parents.stdout.split()[1:] if parents.returncode == 0 else []
    if parent_values != [state["base"]]:
        failures.append("landing parent")
    if git.resolve(repo, f"{commit}^{{tree}}", kind="") != candidate.get("tree"):
        failures.append("candidate tree")

    expected_single = {
        "Invariant-Protocol": str(PROTOCOL_VERSION),
        "Invariant-Change": str(state["change"]),
        "Invariant-Intent": (
            f"{state['intent']['digest']} {state['intent']['supplier']}"
        ),
        "Invariant-Plan": (
            f"{state['recommendation']['id']}@{state['recommendation']['digest']}"
        ),
        "Invariant-Evidence": digest(state.get("evidence", [])),
        "Invariant-Landing-Parent": str(state["base"]),
    }
    for key, expected in expected_single.items():
        if git.trailers(repo, commit, key) != [expected]:
            failures.append(key)

    expected_governance = sorted(str(item) for item in state["governance"]["records"])
    if sorted(git.trailers(repo, commit, "Invariant-Governance")) != expected_governance:
        failures.append("Invariant-Governance")

    expected_decisions = sorted(
        str(grant["decision_digest"])
        for grant in state.get("grants", {}).values()
        if grant.get("status") == "consumed"
    )
    if sorted(git.trailers(repo, commit, "Invariant-Decision")) != expected_decisions:
        failures.append("Invariant-Decision")

    unit_trailers = git.trailers(repo, commit, "Invariant-Unit")
    for unit in candidate.get("units", []):
        attempts = [
            item
            for item in state.get("attempts", {}).values()
            if item.get("unit") == unit and item.get("tip")
        ]
        if not attempts:
            failures.append(f"Invariant-Unit:{unit}")
            continue
        attempt = attempts[-1]
        expected = f"{unit} {attempt['tree']} {attempt['actor']}"
        if expected not in unit_trailers:
            failures.append(f"Invariant-Unit:{unit}")

    expected_reviews = sorted(
        f"{review['digest']} {review['mode']} {review['authority']}"
        for review in state.get("reviews", [])
    )
    if sorted(git.trailers(repo, commit, "Invariant-Review")) != expected_reviews:
        failures.append("Invariant-Review")

    if failures:
        raise InvariantError(
            "Invariant: landing attestation does not bind the completed change",
            code="invalid_attestation",
            data={"commit": commit, "invalid": sorted(set(failures))},
        )


class PublicationService:
    def __init__(self, store: LedgerStore, capabilities: CapabilityService) -> None:
        self.store = store
        self.repository = store.repository
        self.capabilities = capabilities

    def publish(self, change_id: str, *, token: str, operation_id: str) -> Ledger:
        ledger = self.store.load(change_id)
        replay = ledger.event_for(operation_id)
        if replay:
            if replay.kind is EventKind.PUBLICATION_COMPLETED:
                return ledger
            raise InvariantError(
                "Invariant: operation id was reused with different publication input",
                code="invalid_invocation",
            )
        landing = ledger.state.get("landing") or {}
        commit = landing.get("commit", "")
        use = self.capabilities.use(
            change_id,
            token=token,
            capability=CapabilityName.REMOTE_PUBLISH,
            resource=commit,
            operation_id=operation_id,
        )
        target = _remote_push_target(self.repository.root, ledger.state["target"]["branch"])
        consumed = self.capabilities.consume(use, operation_id=f"{operation_id}.consume")
        result = git.run(
            ["push", "--porcelain", "--", target.remote, f"{commit}:{target.merge_ref}"],
            cwd=self.repository.root,
            check=False,
        )
        publication = {
            "commit": commit,
            "remote": target.remote,
            "ref": target.merge_ref,
            "status": "completed" if result.returncode == 0 else "failed",
        }
        kind = EventKind.PUBLICATION_COMPLETED if result.returncode == 0 else EventKind.PUBLICATION_FAILED
        recorded = self.store.append(
            change_id,
            operation_id=operation_id,
            kind=kind,
            actor="kernel:repository/publication",
            payload={"publication": publication},
            expected_head=consumed.head,
            anchors=[commit],
        )
        if result.returncode:
            raise RemotePushFailed(
                "Invariant: remote publication failed; local integration commit is retained",
                lines=[f"LANDED: {commit}", f"REMOTE: {result.stderr or result.stdout}"],
            )
        return recorded


def _remote_push_target(repo: Path, branch: str) -> PushTarget:
    remote = git.run(["config", "--get", f"branch.{branch}.remote"], cwd=repo, check=False).stdout
    merge_ref = git.run(["config", "--get", f"branch.{branch}.merge"], cwd=repo, check=False).stdout
    if not remote or remote == "." or not merge_ref:
        raise Blocked("Invariant: integration branch has no usable upstream", code="remote_upstream_missing")
    remotes = set(git.run(["remote"], cwd=repo).stdout.splitlines())
    if remote not in remotes or not merge_ref.startswith("refs/heads/") or git.run(
        ["check-ref-format", merge_ref], cwd=repo, check=False
    ).returncode:
        raise Blocked("Invariant: configured upstream is invalid", code="remote_upstream_invalid")
    return PushTarget(remote, merge_ref)


def _push_remote(repo: Path, commit: str, target: PushTarget) -> list[str]:
    result = git.run(
        ["push", "--porcelain", "--", target.remote, f"{commit}:{target.merge_ref}"],
        cwd=repo,
        check=False,
    )
    if result.returncode:
        raise RemotePushFailed(
            "Invariant: remote publication failed; local integration commit is retained",
            lines=[f"LANDED: {commit}", f"REMOTE: {result.stderr or result.stdout}"],
        )
    return [f"PUSHED: {commit} -> {target.label}"]
