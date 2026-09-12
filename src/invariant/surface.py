"""Human-surface composition over the protocol-v1 application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from invariant.application import InvariantApplication
from invariant.errors import InvariantError
from invariant.harness import preferences
from invariant.harness.providers import AgentProvider, invoke, invoke_change
from invariant.mechanics import config, git
from invariant.protocol import Outcome, canonical_json


USER_PRINCIPAL = "user:cli"
HARNESS_PRINCIPAL = "harness:cli"


@dataclass(frozen=True)
class SurfaceResult:
    lines: tuple[str, ...]
    data: dict[str, Any]


def settings(repo: Path) -> SurfaceResult:
    application = InvariantApplication.bind(repo, principal=USER_PRINCIPAL)
    policy = application.repository.policy
    values = {
        "authority.intent.suppliers": ",".join(policy.authority.intent.suppliers),
        "authority.resolution.delegation": policy.authority.resolution.delegation,
        "execution.transitions": policy.execution.transitions,
        "integration_branch": policy.integration_branch,
        "publication": policy.publication,
        "parallelism.maximum": str(policy.parallelism.maximum),
        "harness": preferences.repo_harness(repo),
        "mode": preferences.session_mode(repo),
    }
    return SurfaceResult(
        tuple(f"{key.upper()}: {value}" for key, value in values.items()),
        {"settings": values},
    )


def set_value(repo: Path, key: str, value: str) -> SurfaceResult:
    """Apply one local preference or land one deterministic governed policy change."""

    if key == "harness":
        preferences.set_repo_harness(repo, value)
        return SurfaceResult(
            (f"SETTING: harness", f"VALUE: {value}", "SCOPE: this clone"),
            {"key": key, "value": value, "scope": "clone"},
        )
    if key == "mode":
        preferences.set_session_mode(repo, value)
        return SurfaceResult(
            (f"SETTING: mode", f"VALUE: {value}", "SCOPE: this clone"),
            {"key": key, "value": value, "scope": "clone"},
        )

    user = InvariantApplication.bind(repo, principal=USER_PRINCIPAL)
    target, base, _ = user.repository.integration()
    canonical, document, changed = config.updated_document(
        repo, base, target, key, value
    )
    if not changed:
        return SurfaceResult(
            (f"SETTING: {canonical}", f"VALUE: {value}", "STATUS: unchanged"),
            {"key": canonical, "value": value, "changed": False},
        )

    suffix = uuid.uuid4().hex[:12]
    change_id = f"policy-{canonical.replace('.', '-')}-{suffix}"
    attempt_id = f"policy-{suffix}"
    operation = f"set-{suffix}"
    statement = f"Set Invariant policy {canonical} to {value}"
    user.change_open(
        change_id,
        intent=statement,
        supplier=USER_PRINCIPAL,
        paths=[config.CONFIG_PATH.as_posix()],
        operation_id=f"{operation}-open",
    )
    user.change_recommend(change_id, operation_id=f"{operation}-recommend")

    worker = InvariantApplication.bind(repo, principal=HARNESS_PRINCIPAL)
    create_token = _grant(
        worker,
        change_id,
        "worktree.create",
        f"change/{attempt_id}",
        operation_id=f"{operation}-grant-create",
        unit="change",
        attempt=attempt_id,
    )
    created = worker.work_create(
        change_id,
        unit_id="change",
        attempt_id=attempt_id,
        actor=HARNESS_PRINCIPAL,
        token=create_token,
        operation_id=f"{operation}-create",
    )
    _grant(
        worker,
        change_id,
        "worktree.write",
        attempt_id,
        operation_id=f"{operation}-grant-write",
        unit="change",
        attempt=attempt_id,
    )
    worktree = Path(str(created.result["attempt"]["worktree"]))
    config.dump_config_yaml(worktree / config.CONFIG_PATH, document)
    git.run(["add", "--", config.CONFIG_PATH.as_posix()], cwd=worktree)
    git.run(["commit", "-q", "-m", statement], cwd=worktree)
    worker.work_submit(
        change_id,
        attempt_id=attempt_id,
        actor=HARNESS_PRINCIPAL,
        operation_id=f"{operation}-submit",
    )
    converge_token = _grant(
        worker,
        change_id,
        "candidate.converge",
        attempt_id,
        operation_id=f"{operation}-grant-converge",
        attempt=attempt_id,
    )
    worker.candidate_converge(
        change_id,
        attempt_id=attempt_id,
        token=converge_token,
        operation_id=f"{operation}-converge",
    )
    worker.candidate_evidence(
        change_id, tokens={}, operation_id=f"{operation}-evidence"
    )
    candidate = worker.store.load(change_id).state["candidate"]
    requested = worker.capability_request(
        change_id,
        capability="integration.land",
        actor=HARNESS_PRINCIPAL,
        resource=candidate["tree"],
        operation_id=f"{operation}-request-authority",
    )
    action = requested.result.get("action")
    if not isinstance(action, dict):
        raise InvariantError(
            "Invariant: governed policy change did not request user acceptance",
            code="authority_required",
        )
    user.action_respond(
        change_id,
        str(action["id"]),
        response={"bindings": action["bindings"], "resolution": "accepted"},
        actor=USER_PRINCIPAL,
        operation_id=f"{operation}-accept",
    )
    land_token = _grant(
        worker,
        change_id,
        "integration.land",
        candidate["tree"],
        operation_id=f"{operation}-grant-land",
    )
    worker.integration_land(
        change_id,
        token=land_token,
        operation_id=f"{operation}-land",
        subject=statement,
    )
    landed = worker.store.load(change_id).state
    commit = str(landed["landing"]["commit"])
    _cleanup(user, change_id, landed, operation)
    return SurfaceResult(
        (
            f"SETTING: {canonical}",
            f"VALUE: {value}",
            "SCOPE: repository policy",
            f"CHANGE: {change_id}",
            f"COMMIT: {commit}",
            "STATUS: landed",
        ),
        {
            "key": canonical,
            "value": value,
            "scope": "repository",
            "change": change_id,
            "commit": commit,
            "changed": True,
        },
    )


def _grant(
    application: InvariantApplication,
    change_id: str,
    capability: str,
    resource: str,
    *,
    operation_id: str,
    unit: str | None = None,
    attempt: str | None = None,
) -> str:
    result = application.capability_request(
        change_id,
        capability=capability,
        actor=application.store.principal,
        resource=resource,
        unit=unit,
        attempt=attempt,
        operation_id=operation_id,
    )
    token = result.result.get("token")
    if result.outcome is not Outcome.READY or not isinstance(token, str):
        raise InvariantError(
            f"Invariant: {capability} was not granted",
            code="capability_required",
            data=result.result,
        )
    return token


def _cleanup(
    application: InvariantApplication,
    change_id: str,
    state: dict[str, Any],
    operation: str,
) -> None:
    refs = sorted(
        {
            *(str(item["ref"]) for item in state.get("attempts", {}).values()),
            f"refs/invariant/candidates/{change_id}",
        }
    )
    token = _grant(
        application,
        change_id,
        "work.discard",
        canonical_json(refs),
        operation_id=f"{operation}-grant-cleanup",
    )
    application.work_discard(
        change_id,
        refs=refs,
        token=token,
        operation_id=f"{operation}-cleanup",
    )


def execute_agent_change(
    repo: Path,
    provider: AgentProvider,
    session_id: str,
    intent: str,
    paths: list[str],
    *,
    timeout: int = 1800,
) -> SurfaceResult:
    """Run one conversational write through isolated execution and exact landing."""

    suffix = uuid.uuid4().hex[:12]
    change_id = f"session-{session_id.removeprefix('s-')}-{suffix}"
    attempt_id = f"work-{suffix}"
    operation = f"chat-{suffix}"
    claims = paths or ["."]
    user = InvariantApplication.bind(repo, principal=USER_PRINCIPAL)
    user.change_open(
        change_id,
        intent=intent,
        supplier=USER_PRINCIPAL,
        paths=claims,
        operation_id=f"{operation}-open",
    )
    user.change_recommend(change_id, operation_id=f"{operation}-recommend")

    author = f"agent:{provider.value}/{session_id}"
    worker = InvariantApplication.bind(repo, principal=author)
    create_token = _grant(
        worker,
        change_id,
        "worktree.create",
        f"change/{attempt_id}",
        operation_id=f"{operation}-grant-create",
        unit="change",
        attempt=attempt_id,
    )
    created = worker.work_create(
        change_id,
        unit_id="change",
        attempt_id=attempt_id,
        actor=author,
        token=create_token,
        operation_id=f"{operation}-create",
    )
    _grant(
        worker,
        change_id,
        "worktree.write",
        attempt_id,
        operation_id=f"{operation}-grant-write",
        unit="change",
        attempt=attempt_id,
    )
    worktree = Path(str(created.result["attempt"]["worktree"]))
    starting_tip = git.resolve(worktree, "HEAD")
    execution = invoke_change(
        provider,
        worktree,
        (
            "Implement the following user-supplied intent in this isolated Invariant "
            "worktree. Do not commit, move refs, publish, or edit .invariant/runtime. "
            "Stay within these claims: "
            f"{', '.join(claims)}.\n\nIntent:\n{intent.strip()}"
        ),
        timeout=timeout,
    )
    if git.resolve(worktree, "HEAD") != starting_tip:
        raise InvariantError(
            "Invariant: the execution agent moved its worktree ref",
            code="unauthorized_ref_movement",
            data={"change": change_id},
        )
    changed = git.changed_paths(worktree)
    if not changed:
        raise InvariantError(
            "Invariant: the execution agent produced no repository change",
            code="empty_candidate",
            data={"change": change_id},
        )
    git.run(["add", "-A"], cwd=worktree)
    git.run(["commit", "-q", "-m", intent.strip().splitlines()[0][:72]], cwd=worktree)
    worker.work_submit(
        change_id,
        attempt_id=attempt_id,
        actor=author,
        operation_id=f"{operation}-submit",
    )
    converge_token = _grant(
        worker,
        change_id,
        "candidate.converge",
        attempt_id,
        operation_id=f"{operation}-grant-converge",
        attempt=attempt_id,
    )
    worker.candidate_converge(
        change_id,
        attempt_id=attempt_id,
        token=converge_token,
        operation_id=f"{operation}-converge",
    )
    state = worker.store.load(change_id).state
    required = state.get("governance", {}).get("obligations", {}).get(
        "required_verifiers", []
    )
    verifier_tokens = {
        str(locator): _grant(
            worker,
            change_id,
            "verification.run",
            str(locator),
            operation_id=f"{operation}-verify-{index}",
        )
        for index, locator in enumerate(required)
    }
    worker.candidate_evidence(
        change_id,
        tokens=verifier_tokens,
        operation_id=f"{operation}-evidence",
    )
    state = worker.store.load(change_id).state
    pending_reviews = [
        action
        for action in state.get("actions", {}).values()
        if action.get("status") == "pending"
        and action.get("kind") in {"review-semantics", "review-independent"}
    ]
    for index, action in enumerate(pending_reviews):
        _resolve_review(
            repo,
            provider,
            worktree,
            change_id,
            action,
            f"{operation}-review-{index}",
            timeout=timeout,
        )

    state = worker.store.load(change_id).state
    candidate = state["candidate"]
    landing = InvariantApplication.bind(repo, principal=HARNESS_PRINCIPAL)
    requested = landing.capability_request(
        change_id,
        capability="integration.land",
        actor=HARNESS_PRINCIPAL,
        resource=candidate["tree"],
        operation_id=f"{operation}-request-land",
    )
    action = requested.result.get("action")
    if isinstance(action, dict):
        return SurfaceResult(
            (
                f"CHANGE: {change_id}",
                f"CANDIDATE: {candidate['tree']}",
                "STATUS: needs your decision",
                f"REQUEST: :accept {change_id}",
            ),
            {
                "change": change_id,
                "candidate": candidate["tree"],
                "action": action,
                "pending": True,
                "message": execution.message,
            },
        )
    token = requested.result.get("token")
    if not isinstance(token, str):
        raise InvariantError(
            "Invariant: exact candidate is not ready to land",
            code="capability_required",
            data=requested.result,
        )
    landing.integration_land(
        change_id,
        token=token,
        operation_id=f"{operation}-land",
        subject=intent.strip().splitlines()[0][:72],
    )
    completed = landing.store.load(change_id).state
    commit = str(completed["landing"]["commit"])
    _cleanup(user, change_id, completed, operation)
    return SurfaceResult(
        (
            f"CHANGE: {change_id}",
            f"FILES: {', '.join(changed)}",
            f"COMMIT: {commit}",
            "STATUS: landed",
        ),
        {
            "change": change_id,
            "paths": changed,
            "commit": commit,
            "pending": False,
            "message": execution.message,
        },
    )


def _resolve_review(
    repo: Path,
    provider: AgentProvider,
    worktree: Path,
    change_id: str,
    action: dict[str, Any],
    operation: str,
    *,
    timeout: int,
) -> None:
    reviewer = f"agent:{provider.value}/review-{uuid.uuid4().hex[:12]}"
    application = InvariantApplication.bind(repo, principal=reviewer)
    token = _grant(
        application,
        change_id,
        "intent.resolve",
        str(action["id"]),
        operation_id=f"{operation}-grant",
    )
    reviewed = invoke(
        provider,
        worktree,
        (
            "Review this exact candidate independently against the supplied user intent "
            "and repository governance. Inspect the worktree. Do not modify it. Return an "
            "accepted verdict only when no material defect remains.\n\n"
            f"Intent: {action.get('context', {}).get('intent', {}).get('statement', '')}"
        ),
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["verdict", "summary", "defects"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["accepted", "rejected", "uncertain"],
                },
                "summary": {"type": "string"},
                "defects": {"type": "array", "items": {"type": "string"}},
            },
        },
        timeout=timeout,
    )
    response = {
        "bindings": action["bindings"],
        "verdict": reviewed.response.get("verdict"),
        "summary": reviewed.response.get("summary"),
        "defects": reviewed.response.get("defects", []),
    }
    application.action_respond(
        change_id,
        str(action["id"]),
        response=response,
        actor=reviewer,
        token=token,
        operation_id=f"{operation}-respond",
    )
    if response["verdict"] != "accepted":
        raise InvariantError(
            "Invariant: secondary review did not accept the candidate",
            code="review_not_accepted",
            data={"change": change_id, "review": response},
        )


def accept_pending(repo: Path, change_id: str) -> SurfaceResult:
    """Supply direct user acceptance for one exact pending governance candidate."""

    user = InvariantApplication.bind(repo, principal=USER_PRINCIPAL)
    state = user.store.load(change_id).state
    action = next(
        (
            value
            for value in state.get("actions", {}).values()
            if value.get("status") == "pending"
            and value.get("kind") in {"accept-governance", "supply-intent"}
        ),
        None,
    )
    if not isinstance(action, dict):
        raise InvariantError(
            f"Invariant: change '{change_id}' has no pending user acceptance",
            code="invalid_invocation",
        )
    suffix = uuid.uuid4().hex[:12]
    user.action_respond(
        change_id,
        str(action["id"]),
        response={"bindings": action["bindings"], "resolution": "accepted"},
        actor=USER_PRINCIPAL,
        operation_id=f"accept-{suffix}",
    )
    state = user.store.load(change_id).state
    candidate = state["candidate"]
    landing = InvariantApplication.bind(repo, principal=HARNESS_PRINCIPAL)
    token = _grant(
        landing,
        change_id,
        "integration.land",
        candidate["tree"],
        operation_id=f"accept-{suffix}-grant-land",
    )
    landing.integration_land(
        change_id,
        token=token,
        operation_id=f"accept-{suffix}-land",
    )
    completed = landing.store.load(change_id).state
    commit = str(completed["landing"]["commit"])
    _cleanup(user, change_id, completed, f"accept-{suffix}")
    return SurfaceResult(
        (f"CHANGE: {change_id}", f"COMMIT: {commit}", "STATUS: landed"),
        {"change": change_id, "commit": commit, "pending": False},
    )
