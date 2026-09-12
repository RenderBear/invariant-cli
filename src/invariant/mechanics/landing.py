"""Exact candidate landing and separately bounded publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.gateway import CapabilityService
from invariant.ledger import Ledger, LedgerStore
from invariant.mechanics import git
from invariant.mechanics.locks import file_lock
from invariant.protocol import (
    ActionKind,
    CapabilityName,
    EventKind,
    PROTOCOL_VERSION,
    digest,
    is_direct_user_authority,
    require_authority_locator,
    require_id,
)


GOVERNANCE_PATHS = (
    ".invariant/config.yml",
    ".invariant/records",
    ".invariant/SOURCES.yml",
    ".invariant/sources",
    ".invariant/audits",
    ".invariant/discoveries",
)


def _is_governance_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in GOVERNANCE_PATHS)


def governed_worktree_changes(repo: Path) -> list[str]:
    """Return mutable governance paths that differ from accepted HEAD."""

    return [path for path in git.changed_paths(repo) if _is_governance_path(path)]


def _accepted_governance_action(
    action: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    policy_change: bool = False,
) -> bool:
    if (
        action.get("kind") != ActionKind.ACCEPT_GOVERNANCE.value
        or action.get("status") != "responded"
        or action.get("response", {}).get("resolution") != "accepted"
    ):
        return False
    response = action.get("response", {})
    actor = str(response.get("actor") or "")
    principal = str(response.get("principal") or "")
    if is_direct_user_authority(actor, principal):
        return True
    if (
        policy_change
        or action.get("resolver") != "secondary-agent"
        or not actor.startswith("agent:")
    ):
        return False
    authors = {item.get("actor") for item in state.get("attempts", {}).values()}
    principals = {
        item.get("principal") for item in state.get("attempts", {}).values()
    }
    return actor not in authors and principal not in principals


def _authority_action(action: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    if _accepted_governance_action(action, state):
        return True
    response = action.get("response", {})
    return (
        action.get("kind") == ActionKind.SUPPLY_INTENT.value
        and action.get("status") == "responded"
        and response.get("resolution") == "accepted"
        and is_direct_user_authority(response.get("actor"), response.get("principal"))
    )


def _portable_governance_attestation(repo: Path, commit: str) -> bool:
    def one(key: str) -> str | None:
        values = git.trailers(repo, commit, key)
        return values[0] if len(values) == 1 else None

    protocol = one("Invariant-Protocol")
    change = one("Invariant-Change")
    intent = one("Invariant-Intent")
    plan = one("Invariant-Plan")
    evidence = one("Invariant-Evidence")
    landing_parent = one("Invariant-Landing-Parent")
    if None in {protocol, change, intent, plan, evidence, landing_parent}:
        return False
    if protocol != str(PROTOCOL_VERSION):
        return False
    try:
        require_id(change, "attested change")
        intent_digest, supplier, principal = str(intent).split(" ", 2)
        require_authority_locator(supplier, "attested intent supplier")
        require_authority_locator(principal, "attested intent principal")
    except (InvariantError, ValueError):
        return False
    if (
        not is_direct_user_authority(supplier, principal)
        or not re.fullmatch(r"[0-9a-f]{64}", intent_digest)
    ):
        return False
    plan_id, separator, plan_digest = str(plan).rpartition("@")
    if not separator or not re.fullmatch(r"[0-9a-f]{64}", plan_digest):
        return False
    try:
        require_id(plan_id, "attested plan")
    except InvariantError:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence)):
        return False
    parents = git.run(
        ["rev-list", "--parents", "-n", "1", commit], cwd=repo, check=False
    ).stdout.split()
    if len(parents) != 2 or parents[1] != landing_parent:
        return False
    decisions = git.trailers(repo, commit, "Invariant-Decision")
    units = git.trailers(repo, commit, "Invariant-Unit")
    authorities = git.trailers(repo, commit, "Invariant-Authority")
    valid_units = True
    author_actors: set[str] = set()
    author_principals: set[str] = set()
    for value in units:
        parts = value.split(" ")
        if len(parts) != 4 or not re.fullmatch(r"[0-9a-f]{40,64}", parts[1]):
            valid_units = False
            break
        try:
            require_id(parts[0], "attested unit")
            require_authority_locator(parts[2], "attested unit actor")
            require_authority_locator(parts[3], "attested unit principal")
        except InvariantError:
            valid_units = False
            break
        author_actors.add(parts[2])
        author_principals.add(parts[3])
    policy_change = ".invariant/config.yml" in git.changed_paths(
        repo, landing_parent, commit
    )
    delegation = "user"
    if not policy_change:
        policy_result = git.run(
            ["show", f"{landing_parent}:.invariant/config.yml"],
            cwd=repo,
            check=False,
        )
        if not policy_result.returncode:
            try:
                policy_document = yaml.safe_load(policy_result.stdout)
                delegation = str(
                    policy_document["authority"]["resolution"]["delegation"]
                )
            except (KeyError, TypeError, yaml.YAMLError):
                delegation = "user"
    valid_authorities = True
    for value in authorities:
        parts = value.split(" ")
        if len(parts) != 4 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]):
            valid_authorities = False
            break
        try:
            require_id(parts[0], "attested authority action")
            require_authority_locator(parts[2], "attested authority actor")
            require_authority_locator(parts[3], "attested authority principal")
        except InvariantError:
            valid_authorities = False
            break
        direct_user = is_direct_user_authority(parts[2], parts[3])
        delegated = (
            not policy_change
            and delegation == "secondary-agent"
            and parts[2].startswith("agent:")
            and parts[2] not in author_actors
            and parts[3] not in author_principals
        )
        if not direct_user and not delegated:
            valid_authorities = False
            break
    return bool(decisions and units and authorities) and valid_units and valid_authorities and all(
        re.fullmatch(r"[0-9a-f]{64}", value) for value in decisions
    )


def validate_governance_history(
    repo: Path,
    tip: str,
    states: Mapping[str, Mapping[str, Any]],
) -> None:
    """Require every post-initialization governance change to be attested."""

    baseline_rows = git.run(
        [
            "log",
            "--first-parent",
            "--reverse",
            "--format=%H",
            "--diff-filter=A",
            tip,
            "--",
            ".invariant/config.yml",
        ],
        cwd=repo,
        check=False,
    ).stdout.splitlines()
    if not baseline_rows:
        raise InvariantError(
            "Invariant: integration history has no governance trust root",
            code="not_initialized",
        )
    baseline = baseline_rows[0]
    baseline_governance = [
        path
        for path in git.run(
            ["ls-tree", "-r", "--name-only", baseline, "--", *GOVERNANCE_PATHS],
            cwd=repo,
        ).stdout.splitlines()
        if path
    ]
    if baseline_governance != [".invariant/config.yml"]:
        raise InvariantError(
            "Invariant: governance trust root must introduce only config.yml",
            code="invalid_attestation",
            data={"commit": baseline, "paths": baseline_governance},
        )
    commits = git.run(
        [
            "log",
            "--first-parent",
            "--reverse",
            "--format=%H",
            f"{baseline}..{tip}",
            "--",
            *GOVERNANCE_PATHS,
        ],
        cwd=repo,
        check=False,
    ).stdout.splitlines()
    invalid: list[str] = []
    for commit in commits:
        changes = git.trailers(repo, commit, "Invariant-Change")
        state = states.get(changes[0]) if len(changes) == 1 else None
        if state is not None:
            landing = state.get("landing") or {}
            policy_change = ".invariant/config.yml" in git.changed_paths(
                repo, str(state.get("base")), commit
            )
            accepted = any(
                _accepted_governance_action(
                    action,
                    state,
                    policy_change=policy_change,
                )
                for action in state.get("actions", {}).values()
            )
            if (
                state.get("stage") != "completed"
                or landing.get("commit") != commit
                or not is_direct_user_authority(
                    state.get("intent", {}).get("supplier"),
                    state.get("intent", {}).get("principal"),
                )
                or not accepted
            ):
                invalid.append(commit)
                continue
            try:
                validate_landing_attestation(repo, state)
            except InvariantError:
                invalid.append(commit)
            continue
        if not _portable_governance_attestation(repo, commit):
            invalid.append(commit)
    if invalid:
        raise InvariantError(
            "Invariant: integration history contains unattested governance changes",
            code="invalid_attestation",
            data={"commits": invalid},
        )


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
            "Invariant-Intent: "
            f"{state['intent']['digest']} {state['intent']['supplier']} "
            f"{state['intent']['principal']}",
            f"Invariant-Plan: {recommendation['id']}@{recommendation['digest']}",
        ]
        for unit in recommendation["units"]:
            attempts = [item for item in state["attempts"].values() if item["unit"] == unit["id"] and item.get("tip")]
            if attempts:
                attempt = attempts[-1]
                trailers.append(
                    f"Invariant-Unit: {unit['id']} {attempt['tree']} "
                    f"{attempt['actor']} {attempt['principal']}"
                )
        for grant in state["grants"].values():
            if grant.get("status") == "consumed":
                trailers.append(f"Invariant-Decision: {grant['decision_digest']}")
        trailers.append(f"Invariant-Decision: {landing_decision}")
        for action_id, action in sorted(state.get("actions", {}).items()):
            response = action.get("response", {})
            if _authority_action(action, state):
                trailers.append(
                    f"Invariant-Authority: {action_id} {response['event']} "
                    f"{response['actor']} {response['principal']}"
                )
        for record in state["governance"]["records"]:
            trailers.append(f"Invariant-Governance: {record}")
        evidence_digest = digest(state.get("evidence", []))
        trailers.append(f"Invariant-Evidence: {evidence_digest}")
        for review in state.get("reviews", []):
            trailers.append(
                f"Invariant-Review: {review['digest']} {review['mode']} "
                f"{review['authority']} {review['principal']}"
            )
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
            f"{state['intent']['digest']} {state['intent']['supplier']} "
            f"{state['intent']['principal']}"
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

    landing_sequence = landing.get("sequence")
    operations = state.get("operations", {})
    if not isinstance(landing_sequence, int) or not isinstance(operations, Mapping):
        failures.append("landing event")
        landing_sequence = -1
        operations = {}

    def consumed_before_landing(grant: Mapping[str, Any]) -> bool:
        closed_by = grant.get("closed_by")
        operation = operations.get(closed_by) if isinstance(closed_by, str) else None
        sequence = operation.get("sequence") if isinstance(operation, Mapping) else None
        return (
            grant.get("status") == "consumed"
            and isinstance(sequence, int)
            and sequence <= landing_sequence
        )

    expected_decisions = sorted(
        str(grant["decision_digest"])
        for grant in state.get("grants", {}).values()
        if consumed_before_landing(grant)
    )
    if sorted(git.trailers(repo, commit, "Invariant-Decision")) != expected_decisions:
        failures.append("Invariant-Decision")

    expected_authorities = sorted(
        f"{action_id} {action['response']['event']} "
        f"{action['response']['actor']} {action['response']['principal']}"
        for action_id, action in state.get("actions", {}).items()
        if _authority_action(action, state)
    )
    if sorted(git.trailers(repo, commit, "Invariant-Authority")) != expected_authorities:
        failures.append("Invariant-Authority")

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
        expected = (
            f"{unit} {attempt['tree']} {attempt['actor']} {attempt['principal']}"
        )
        if expected not in unit_trailers:
            failures.append(f"Invariant-Unit:{unit}")

    expected_reviews = sorted(
        f"{review['digest']} {review['mode']} {review['authority']} {review['principal']}"
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
