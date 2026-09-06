from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from invariant import adapters
from invariant.adapters.base import CANDIDATE_EVIDENCED, TASK_CREATED
from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.mechanics import config, coordinate, git, governance, landing, receipts
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.semantics import guidance
from invariant.semantics.models import Assessment
from invariant.semantics.review import CandidateReview, candidate_review_schema


@dataclass(frozen=True)
class FlowResult:
    lines: list[str]
    data: dict[str, object]
    outcome: str = "completed"


def _valid_boundary(value: str) -> bool:
    return value in {"no-record", "recorded", "unresolved"} or (
        value.startswith("audit:") and git.valid_id(value.removeprefix("audit:"))
    )


def _target_config(repo: Path, target: str | None = None) -> config.Config:
    previous = os.environ.get("INVARIANT_INTEGRATION_TARGET")
    if target:
        os.environ["INVARIANT_INTEGRATION_TARGET"] = target
    try:
        return config.resolve(repo)
    finally:
        if target:
            if previous is None:
                os.environ.pop("INVARIANT_INTEGRATION_TARGET", None)
            else:
                os.environ["INVARIANT_INTEGRATION_TARGET"] = previous


def _branch_name(repo: Path, task: str, head: str) -> str:
    nonce = git.hash_text(
        repo,
        f"{git.common_dir(repo)}\n{task}\n{head}\n{os.getpid()}-{time.time_ns()}\n",
    )[:12]
    return f"invariant/work/{task}-{nonce}"


def _worktree_path(repo: Path, branch: str) -> Path:
    name = branch.removeprefix("invariant/work/")
    return coordinate.ensure_runtime(repo) / "worktrees" / name


def _create_branch(repo: Path, branch: str, target: str) -> Path:
    if git.branch_exists(repo, branch):
        raise InvariantError(f"Invariant: generated task branch '{branch}' already exists")
    worktree = _worktree_path(repo, branch)
    if worktree.exists():
        raise InvariantError(
            f"Invariant: generated task worktree '{worktree}' already exists",
            code="task_worktree_exists",
        )
    worktree.parent.mkdir(parents=True, exist_ok=True)
    git.run(
        [
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(worktree),
            f"refs/heads/{target}",
        ],
        cwd=repo,
    )
    return worktree.resolve()


def _validate_adapter_receipt(receipt: dict[str, object]) -> None:
    identifiers = adapters.enabled(receipt)
    adapters.validate(identifiers)
    if receipt.get("adapter_digest") != adapters.digest(identifiers):
        raise Blocked("STALE: task adapter implementation changed", code="stale_receipt")


def _blocking_hook_requests(receipt: Mapping[str, object]) -> list[dict[str, object]]:
    return [item for item in adapters.pending(receipt) if item.get("blocking", True)]


def _retained_discoveries(receipt: Mapping[str, object]) -> list[str]:
    session = (
        receipt.get("governance_run")
        if isinstance(receipt.get("governance_run"), dict)
        else {}
    )
    coverage = session.get("coverage") if isinstance(session.get("coverage"), dict) else {}
    findings = (
        coverage.get("findings")
        if isinstance(coverage.get("findings"), dict)
        else {}
    )
    return sorted(
        {
            str(value.get("retained_as"))
            for value in findings.values()
            if isinstance(value, dict) and value.get("status") == "retained"
        }
    )


def _assurance_summary(
    evidence: Iterable[Mapping[str, object]],
    requests: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    values = list(evidence)
    structural = [
        str(item.get("evidence_id"))
        for item in values
        if item.get("kind") == "state_validation" and item.get("evidence_id")
    ]
    behavioral = [
        str(item.get("evidence_id"))
        for item in values
        if str(item.get("evidence_id") or "").startswith("verification:")
    ]
    review_ids = [
        str(item.get("id"))
        for item in requests
        if item.get("phase") == CANDIDATE_EVIDENCED and item.get("id")
    ]
    return {
        "structural": {"status": "passed", "evidence_ids": structural},
        "behavioral": {
            "status": "passed" if behavioral else "not_required",
            "evidence_ids": behavioral,
        },
        "semantic": {
            "status": "pending" if review_ids else "not_required",
            "review_ids": review_ids,
        },
    }


def _accept_semantic_assurance(receipt: dict[str, object]) -> None:
    assurance = receipt.get("assurance")
    if not isinstance(assurance, dict):
        return
    semantic = assurance.get("semantic")
    if not isinstance(semantic, dict) or semantic.get("status") != "pending":
        return
    assurance["semantic"] = {**semantic, "status": "accepted"}
    receipt["assurance"] = assurance


def _record_completion(
    repo: Path,
    task: str,
    receipt: dict[str, object],
    assessment: Assessment,
    candidate_tree: str | None,
) -> None:
    """Persist the final semantic disposition before the task is archived."""

    receipt["resolved_boundary"] = assessment.boundary.disposition
    if candidate_tree:
        receipt["candidate_tree"] = candidate_tree
    assurance = receipt.get("assurance")
    if not isinstance(assurance, dict):
        assurance = {
            "structural": {"status": "passed", "evidence_ids": []},
            "behavioral": {
                "status": "passed" if assessment.checks else "not_required",
                "evidence_ids": [],
            },
            "semantic": {
                "status": "accepted" if assessment.architecture_reviews else "not_required",
                "review_ids": [],
            },
        }
    semantic = assurance.get("semantic")
    if isinstance(semantic, dict) and semantic.get("status") == "pending":
        assurance["semantic"] = {**semantic, "status": "accepted"}
    receipt["assurance"] = assurance
    receipts.save(repo, task, receipt)


def _hook_lines(receipt: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for request in adapters.pending(receipt):
        lines.append(
            f"ACTION: {request.get('id')} — {request.get('kind')}"
        )
    return lines


def _assurance_lines(assurance: object) -> list[str]:
    if not isinstance(assurance, Mapping):
        return []
    return [
        f"ASSURANCE-{name.upper()}: {value.get('status') or 'unknown'}"
        for name in ("structural", "behavioral", "semantic")
        if isinstance((value := assurance.get(name)), Mapping)
    ]


def _completion_delta_lines(
    repo: Path,
    task: str,
    *,
    candidate_tree: str,
    evidence_count: int,
) -> list[str]:
    completed = receipts.load_completed(repo, task)
    if completed is None:
        raise InvariantError(f"Invariant: completed task '{task}' has no archived receipt")
    return [
        f"TASK: {task}",
        "STATUS: completed",
        f"LANDING-COMMIT: {completed.get('completed_commit') or 'unknown'}",
        f"BOUNDARY: {completed.get('resolved_boundary') or 'unresolved'}",
        f"CANDIDATE-TREE: {candidate_tree}",
        *_assurance_lines(completed.get("assurance")),
        f"EVIDENCE: {evidence_count} retained — invariant task evidence {task}",
    ]


def _transition(
    receipt: dict[str, object], stage: str, branch: str, worktree: str
) -> dict[str, object]:
    receipt["lifecycle"] = {
        "stage": stage,
        "branch": branch,
        "worktree": worktree,
    }
    return receipt


def _activate(
    repo: Path,
    task: str,
    receipt: dict[str, object],
    *,
    execution: str,
) -> list[str]:
    target = str(receipt["integration_target"])
    head = str(receipt["integration_head"])
    if head == "unborn":
        branch = target
        stage = "implementing-unborn"
        worktree = repo
    else:
        branch = _branch_name(repo, task, head)
        worktree = _worktree_path(repo, branch)
        if execution == "assisted":
            stage = "awaiting-branch"
        else:
            try:
                worktree = _create_branch(repo, branch, target)
            except Exception:
                receipts.invalidate(repo, task)
                raise
            stage = "implementing"
    receipt = receipts.set_lifecycle(repo, task, stage, branch, str(worktree))
    output = _status_lines(repo, receipt)
    output.append(
        f"NEXT: invariant task continue {task} --apply"
        if stage == "awaiting-branch"
        else f"NEXT: implement and commit the requested change in {worktree}"
    )
    output.append(f"GUIDANCE: invariant task guidance {task}")
    return output


def begin(
    repo: Path,
    task: str,
    *,
    goal: str,
    boundary: str,
    paths: Iterable[str] = (),
    interfaces: Iterable[str] = (),
    domains: Iterable[str] = (),
    adapter_inputs: Mapping[str, str | None] | None = None,
    adapter_overrides: Mapping[str, bool] | None = None,
) -> list[str]:
    repo = git.primary_worktree(repo)
    git.require_capabilities(repo)
    if not git.valid_id(task):
        raise InvariantError(f"Invariant: invalid task id '{task}'")
    if not goal:
        raise InvariantError("Invariant: task begin requires --goal")
    if not _valid_boundary(boundary):
        raise InvariantError("Invariant: task begin requires a valid --boundary")
    path = receipts.receipt_path(repo, task)
    if path.is_file():
        receipt, _ = receipts.check_receipt(
            repo,
            task,
            goal=goal,
            paths=paths,
            interfaces=interfaces,
            domains=domains,
        )
        _validate_adapter_receipt(receipt)
        return [*_status_lines(repo, receipt), *_hook_lines(receipt)]

    resolved = config.resolve(repo)
    selected_adapters = set(resolved.adapters.enabled)
    for identifier, enabled in (adapter_overrides or {}).items():
        if enabled:
            selected_adapters.add(identifier)
        else:
            selected_adapters.discard(identifier)
    selected_adapters.update(
        identifier for identifier, source in (adapter_inputs or {}).items() if source
    )
    adapter_ids = tuple(sorted(selected_adapters))
    adapters.validate(adapter_ids)
    receipt, _ = receipts.open_receipt(
        repo,
        task,
        goal=goal,
        boundary=boundary,
        paths=paths,
        interfaces=interfaces,
        domains=domains,
        adapters=adapter_ids,
    )
    receipt["adapter_digest"] = adapters.digest(adapter_ids)
    receipts.save(repo, task, receipt)
    _activate(repo, task, receipt, execution=resolved.execution)
    receipt = receipts.load(repo, task)
    adapters.run_hook(
        receipts.task_root(repo, task), receipt, TASK_CREATED, adapter_inputs or {}
    )
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    if _blocking_hook_requests(receipt) and lifecycle.get("stage") in {
        "implementing",
        "implementing-unborn",
    }:
        receipt = _transition(
            receipt,
            "briefing",
            str(lifecycle.get("branch") or ""),
            str(lifecycle.get("worktree") or repo),
        )
    if not _blocking_hook_requests(receipt):
        receipt.pop("goal", None)
    receipts.save(repo, task, receipt)
    return [*_status_lines(repo, receipt), *_hook_lines(receipt)]


def _status_lines(repo: Path, receipt: dict[str, object]) -> list[str]:
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "briefed")
    branch = str(lifecycle.get("branch") or "")
    target = str(receipt.get("integration_target") or "")
    target_head = git.resolve(repo, f"refs/heads/{target}") or "unborn"
    branch_head = git.resolve(repo, f"refs/heads/{branch}") if branch else None
    adapter_ids = adapters.enabled(receipt)
    output = [
        f"TASK: {receipt.get('task')}",
        f"STATUS: {stage}",
        f"TARGET: {target}",
        f"TARGET-HEAD: {target_head}",
        f"BASE: {receipt.get('integration_head')}",
        f"GOAL-DIGEST: {receipt.get('goal_digest')}",
        f"BRANCH: {branch or 'none'}",
        f"BRANCH-HEAD: {branch_head or 'absent'}",
        f"WORKTREE: {lifecycle.get('worktree') or 'unknown'}",
        f"ADAPTERS: {', '.join(adapter_ids) or 'none'}",
    ]
    assurance = receipt.get("assurance")
    if isinstance(assurance, dict):
        for name in ("structural", "behavioral", "semantic"):
            value = assurance.get(name)
            if isinstance(value, dict):
                output.append(
                    f"ASSURANCE-{name.upper()}: {value.get('status') or 'unknown'}"
                )
        semantic = assurance.get("semantic")
        if isinstance(semantic, dict) and semantic.get("review_mode"):
            output.append(
                "SEMANTIC-REVIEW: "
                f"{semantic.get('review_mode')} — {semantic.get('authority') or 'unknown'}"
            )
    return output


def _completed_status_lines(receipt: dict[str, object]) -> list[str]:
    classification = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    governance_run = (
        receipt.get("governance_run")
        if isinstance(receipt.get("governance_run"), dict)
        else {}
    )
    output = [
        f"TASK: {receipt.get('task')}",
        "STATUS: completed",
        f"TARGET: {receipt.get('integration_target')}",
        f"LANDING-COMMIT: {receipt.get('completed_commit')}",
        f"GOAL-DIGEST: {receipt.get('goal_digest')}",
        f"BOUNDARY-INITIAL: {classification.get('boundary') or 'unresolved'}",
        f"BOUNDARY: {receipt.get('resolved_boundary') or 'unresolved'}",
        "CANDIDATE-TREE: "
        + str(
            receipt.get("candidate_tree")
            or receipt.get("review_candidate_tree")
            or "unknown"
        ),
    ]
    if governance_run:
        output.extend(
            [
                f"AUDIT: {governance_run.get('audit') or 'none'}",
                "SELECTED-FINDINGS: "
                + ", ".join(
                    str(item) for item in governance_run.get("selected_findings", [])
                ),
            ]
        )
    assurance = receipt.get("assurance")
    if isinstance(assurance, dict):
        for name in ("structural", "behavioral", "semantic"):
            value = assurance.get(name)
            if isinstance(value, dict):
                output.append(
                    f"ASSURANCE-{name.upper()}: {value.get('status') or 'unknown'}"
                )
        semantic = assurance.get("semantic")
        if isinstance(semantic, dict) and semantic.get("review_mode"):
            output.append(
                "SEMANTIC-REVIEW: "
                f"{semantic.get('review_mode')} — {semantic.get('authority') or 'unknown'}"
            )
    return output


def status(repo: Path, task: str) -> list[str]:
    if not git.valid_id(task):
        raise InvariantError(f"Invariant: invalid task id '{task}'")
    path = receipts.receipt_path(repo, task)
    if not path.is_file():
        completed = receipts.load_completed(repo, task)
        if completed is not None:
            return _completed_status_lines(completed)
        raise Blocked(f"TASK: {task}\nSTATUS: absent", code="missing_task")
    receipt = receipts.load(repo, task)
    return [*_status_lines(repo, receipt), *_hook_lines(receipt)]


def check(
    repo: Path,
    task: str,
    *,
    goal: str | None,
    goal_digest: str | None,
    compatible_goal: bool,
    paths: Iterable[str] | None,
    interfaces: Iterable[str] | None,
    domains: Iterable[str] | None,
) -> list[str]:
    receipt, lines = receipts.check_receipt(
        repo,
        task,
        goal=goal,
        goal_digest=goal_digest,
        compatible_goal=compatible_goal,
        paths=paths,
        interfaces=interfaces,
        domains=domains,
    )
    return [*lines, *_status_lines(repo, receipt)]


def respond(repo: Path, task: str, request_id: str, source: str) -> FlowResult:
    """Resolve one hook action and advance automatically when all gates are ready."""

    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    matches = [item for item in adapters.pending(receipt) if item.get("id") == request_id]
    if len(matches) != 1:
        raise InvariantError(
            f"Invariant: task '{task}' has no pending action '{request_id}'",
            code="unknown_action",
        )
    request = matches[0]
    candidate_tree = str(receipt.get("review_candidate_tree") or "")
    evidence_ids = [
        str(item)
        for item in receipt.get("candidate_evidence_ids", [])
        if isinstance(item, str)
    ]
    adapter = str(request.get("adapter") or "")
    phase = str(request.get("phase") or "")
    existing_core = [
        item for item in adapters.pending(receipt)
        if item.get("adapter") == "core" and item.get("id") != request_id
    ]
    if adapter == "core":
        review = _apply_core_review(repo, task, request, source)
        receipt["semantic_review"] = {
            "review_id": review.review_id,
            "authority": review.authority,
            "review_mode": review.review_mode,
            "summary": review.summary,
        }
        assurance = receipt.get("assurance")
        if isinstance(assurance, dict):
            semantic = assurance.get("semantic")
            if isinstance(semantic, dict):
                assurance["semantic"] = {
                    **semantic,
                    "authority": review.authority,
                    "review_mode": review.review_mode,
                }
                receipt["assurance"] = assurance
        receipt["hook_requests"] = [
            item for item in adapters.pending(receipt) if item.get("id") != request_id
        ]
    else:
        context = request.get("context") if isinstance(request.get("context"), dict) else {}
        candidate_tree = str(context.get("candidate_tree") or "") or None
        adapters.run_hook(
            receipts.task_root(repo, task),
            receipt,
            phase,
            {adapter: source},
            candidate_tree=candidate_tree,
            evidence=tuple(
                item
                for item in context.get("evidence", [])
                if isinstance(item, dict)
            ),
            retained_discoveries=tuple(
                str(item)
                for item in context.get("retained_discoveries", [])
                if isinstance(item, str)
            ),
        )
        receipt["hook_requests"] = [*adapters.pending(receipt), *existing_core]
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    if not _blocking_hook_requests(receipt) and stage == "briefing":
        receipt.pop("goal", None)
        active_stage = (
            "implementing-unborn"
            if str(receipt.get("integration_head")) == "unborn"
            else "implementing"
        )
        receipt = _transition(
            receipt,
            active_stage,
            str(lifecycle.get("branch") or ""),
            str(lifecycle.get("worktree") or repo),
        )
        receipts.save(repo, task, receipt)
        return FlowResult(
            [
                f"RESOLVED: {request_id}",
                f"TASK: {task}",
                f"STATUS: {active_stage}",
                f"WORKTREE: {lifecycle.get('worktree') or repo}",
            ],
            {"task": task, "stage": active_stage, "actions": []},
            "ready",
        )
    if not _blocking_hook_requests(receipt) and stage == "awaiting-review":
        active_stage = (
            "implementing-unborn"
            if str(receipt.get("integration_head")) == "unborn"
            else "implementing"
        )
        receipt = _transition(
            receipt,
            active_stage,
            str(lifecycle.get("branch") or ""),
            str(lifecycle.get("worktree") or repo),
        )
        _accept_semantic_assurance(receipt)
        receipts.save(repo, task, receipt)
        assurance = receipt.get("assurance", {})
        finish(
            repo,
            task,
            assessment_path=str(_assessment_for_completion(repo, task)),
            subject=str(receipt.get("finish_subject") or f"Invariant task {task}"),
        )
        return FlowResult(
            [
                f"RESOLVED: {request_id}",
                *_completion_delta_lines(
                    repo,
                    task,
                    candidate_tree=candidate_tree or "unknown",
                    evidence_count=len(evidence_ids),
                ),
            ],
            {
                "task": task,
                "stage": "completed",
                "actions": [],
                "candidate_tree": candidate_tree,
                "evidence_ids": evidence_ids,
                "assurance": assurance,
            },
        )
    receipts.save(repo, task, receipt)
    actions = adapters.pending(receipt)
    return FlowResult(
        [
            f"RESOLVED: {request_id}",
            f"TASK: {task}",
            f"STATUS: {stage}",
            *_assurance_lines(receipt.get("assurance")),
            *_hook_lines(receipt),
        ],
        {
            "task": task,
            "stage": stage,
            "actions": adapters.action_descriptors(receipt),
            "candidate_tree": candidate_tree,
            "evidence_ids": evidence_ids,
            "assurance": receipt.get("assurance", {}),
        },
        "needs_input" if actions else "ready",
    )


def _path_covered(path: str, claims: Iterable[str]) -> bool:
    return any(path == claim or path.startswith(claim + "/") for claim in claims)


def _actual_paths(repo: Path, stage: str, base: str, branch: str) -> tuple[str | None, list[str]]:
    if stage == "implementing":
        branch_ref = git.resolve(repo, f"refs/heads/{branch}")
        if not branch_ref:
            raise Blocked(f"Invariant: task branch '{branch}' is missing")
        worktree = git.worktree_for_branch(repo, branch)
        if worktree and not git.worktree_clean(worktree):
            raise Blocked(
                "Invariant: task worktree has uncommitted changes; commit the implementation before finishing",
                code="dirty_worktree",
            )
        return branch_ref, git.changed_paths(repo, base, branch_ref)
    values: list[str] = []
    for args in (
        ["diff", "--name-only", "--cached", "--"],
        ["diff", "--name-only", "--"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        values.extend(git.run(args, cwd=repo, check=False).stdout.splitlines())
    return None, sorted(set(filter(None, values)))


def _candidate_repo(repo: Path, active_stage: str, branch: str) -> Path:
    if active_stage == "implementing-unborn":
        return repo
    worktree = git.worktree_for_branch(repo, branch)
    if worktree is None:
        raise Blocked(
            f"Invariant: task branch '{branch}' has no checked-out worktree",
            code="missing_task_worktree",
        )
    return worktree.resolve()


def _require_lifecycle_checkout(repo: Path, branch: str) -> None:
    worktree = git.worktree_for_branch(repo, branch)
    primary = git.primary_worktree(repo).resolve()
    if worktree is not None and worktree.resolve() == repo.resolve() and repo.resolve() != primary:
        raise Blocked(
            "Invariant: finish must run outside the managed task worktree so successful cleanup is safe",
            code="wrong_worktree",
            lines=[f"PRIMARY-CHECKOUT: {primary}", f"NEXT: run invariant task finish from {primary}"],
        )


def _complete_task(repo: Path, task: str, active_stage: str, branch: str, target: str) -> None:
    if active_stage == "implementing":
        primary = git.primary_worktree(repo).resolve()
        worktree = git.worktree_for_branch(repo, branch)
        if worktree is not None and worktree.resolve() != primary:
            removed = git.run(
                ["worktree", "remove", str(worktree)], cwd=primary, check=False
            )
            if removed.returncode:
                receipts.set_lifecycle(repo, task, "cleanup-required", branch, str(worktree))
                detail = removed.stderr or removed.stdout or "Git refused worktree removal"
                raise Blocked(
                    f"Invariant: landed successfully but could not remove task worktree '{worktree}'",
                    lines=[f"GIT: {detail}"],
                )
        elif worktree is not None and git.current_branch(primary) == branch:
            git.run(["switch", "-q", target], cwd=primary)
        deleted = git.run(["branch", "-d", branch], cwd=primary, check=False)
        if deleted.returncode:
            remaining = git.worktree_for_branch(primary, branch)
            receipts.set_lifecycle(
                repo,
                task,
                "cleanup-required",
                branch,
                str(remaining or primary),
            )
            raise Blocked(
                f"Invariant: landed successfully but could not remove task branch '{branch}'"
            )
    landed_commit = git.resolve(repo, f"refs/heads/{target}")
    if not landed_commit:
        raise InvariantError(f"Invariant: completed integration branch '{target}' has no commit")
    receipts.complete(repo, task, landed_commit)


def finish(
    repo: Path,
    task: str,
    *,
    assessment_path: str,
    subject: str | None = None,
    checks: Iterable[str] = (),
    adapter_inputs: Mapping[str, str | None] | None = None,
    continuation_apply: bool = False,
) -> list[str]:
    assessment = Assessment.load(assessment_path)
    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    if stage not in {"implementing", "implementing-unborn", "awaiting-review"}:
        raise Blocked(f"Invariant: task '{task}' is not ready to finish (stage '{stage}')")
    active_stage = "implementing-unborn" if str(receipt.get("integration_head")) == "unborn" else "implementing"
    branch = str(lifecycle.get("branch") or "")
    target = str(receipt.get("integration_target") or "")
    base = str(receipt.get("integration_head") or "")
    cached_goal = str(receipt.get("goal_digest") or "")
    change_classification = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    cached_boundary = str(change_classification.get("boundary") or "")
    if active_stage == "implementing":
        _require_lifecycle_checkout(repo, branch)
    if assessment.goal_digest != cached_goal:
        raise Blocked("Invariant: assessment goal_digest does not match the active task", code="invalid_assessment")
    if cached_boundary != "unresolved" and assessment.boundary.disposition != cached_boundary:
        raise Blocked(
            f"Invariant: assessment boundary '{assessment.boundary.disposition}' differs from cached semantic boundary '{cached_boundary}'",
            code="invalid_assessment",
        )
    if not assessment.paths:
        raise InvariantError("Invariant: assessment must list the candidate paths")
    if assessment.boundary.disposition == "recorded" and not assessment.governance:
        raise InvariantError("Invariant: a recorded boundary requires governance references")

    resolved = _target_config(repo, target)
    if resolved.integration_branch != target:
        raise Blocked(
            f"Invariant: integration target changed from '{target}' to '{resolved.integration_branch}'"
        )
    branch_ref, actual_paths = _actual_paths(repo, active_stage, base, branch)
    if not actual_paths:
        raise Blocked("Invariant: task candidate contains no changes")
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
    cached_domain_values = scope.get("domains", [])
    cached_domains = (
        {str(item) for item in cached_domain_values}
        if isinstance(cached_domain_values, list)
        else set()
    )
    expanded_domains = set(assessment.domains) - cached_domains
    domains_at_base = (
        {str(row.get("id")) for row in governance.domains(repo, base) if row.get("id")}
        if base != "unborn"
        else set()
    )
    invalid_expansion = expanded_domains.intersection(domains_at_base)
    establishing_domains = ".invariant/DOMAINS.yml" in actual_paths
    if expanded_domains and (
        invalid_expansion
        or not establishing_domains
        or assessment.boundary.disposition != "recorded"
    ):
        domain = sorted(invalid_expansion or expanded_domains)[0]
        raise Blocked(f"STALE: domain scope expanded to {domain}", code="stale_receipt")
    receipts.check_receipt(
        repo,
        task,
        goal_digest=assessment.goal_digest,
        interfaces=assessment.interfaces,
        domains=[domain for domain in assessment.domains if domain in cached_domains],
    )
    for path in actual_paths:
        if not _path_covered(path, assessment.paths):
            raise Blocked(
                f"Invariant: candidate path '{path}' is absent from the assessment",
                code="invalid_assessment",
            )

    candidate_repo = _candidate_repo(repo, active_stage, branch)
    reach_lines = governance.reach(
        candidate_repo,
        paths=actual_paths,
        base=None if active_stage == "implementing-unborn" else base,
        root_mode=active_stage == "implementing-unborn",
        domains_selected=assessment.domains,
        interfaces=assessment.interfaces,
    )
    scopes = tuple(
        line.removeprefix("TOPOLOGY: ") for line in reach_lines if line.startswith("TOPOLOGY: ")
    ) or ("area.root",)
    expected_tree = str(receipt.get("review_candidate_tree") or "") or None
    if adapters.enabled(receipt):
        candidate_tree = landing.prospective_tree(repo, target, None if active_stage == "implementing-unborn" else branch)
        adapters.run_hook(
            receipts.task_root(repo, task),
            receipt,
            CANDIDATE_EVIDENCED,
            adapter_inputs or {},
            candidate_tree=candidate_tree,
        )
        if _blocking_hook_requests(receipt):
            receipt = _transition(
                receipt,
                "awaiting-review",
                branch,
                str(lifecycle.get("worktree") or repo),
            )
            receipts.save(repo, task, receipt)
            raise Blocked(
                "Invariant: exact-candidate adapter review is required before landing",
                code="hook_input_required",
                lines=[
                    f"TASK: {task}",
                    "STATUS: awaiting-review",
                    f"CANDIDATE-TREE: {candidate_tree}",
                    *_hook_lines(receipt),
                ],
                data={
                    "task": task,
                    "stage": "awaiting-review",
                    "actions": adapters.action_descriptors(receipt),
                },
            )
        if stage == "awaiting-review":
            _transition(
                receipt, active_stage, branch, str(lifecycle.get("worktree") or repo)
            )
            receipts.save(repo, task, receipt)
        expected_tree = candidate_tree

    combined_checks = tuple(sorted(set([*assessment.checks, *checks])))
    request = landing.LandRequest(
        mode="direct" if active_stage == "implementing-unborn" else "merge",
        merge_branch=None if active_stage == "implementing-unborn" else branch,
        subject=subject or f"Invariant task {task}",
        units=(task,),
        scopes=scopes,
        paths=tuple(actual_paths) if active_stage == "implementing-unborn" else (),
        domains=tuple(assessment.domains),
        interfaces=tuple(assessment.interfaces),
        governance_refs=tuple(assessment.governance),
        reviewed=tuple(assessment.architecture_reviews),
        boundary=assessment.boundary.disposition,
        checks=combined_checks,
        target=target,
        allow_open=assessment.allow_open,
        expected_tree=expected_tree,
    )
    if resolved.execution == "assisted" and not continuation_apply:
        local = receipts.task_root(repo, task)
        local.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(assessment_path, local / "pending-assessment.yml")
        dump_yaml(local / "pending-finish.yml", {"subject": request.subject, "checks": list(checks)})
        _transition(
            receipt,
            "awaiting-landing",
            branch,
            str(lifecycle.get("worktree") or repo),
        )
        receipts.save(repo, task, receipt)
        raise Blocked(
            "Invariant: landing awaits explicit continuation",
            code="lifecycle_paused",
            lines=[
                *reach_lines,
                f"TASK: {task}",
                "STATUS: awaiting-landing",
                f"PROPOSED: verify the exact candidate and atomically land it onto {target}",
                f"NEXT: invariant task continue {task} --apply",
            ],
        )
    try:
        output = landing.verify_and_land(repo, request)
    except RemotePushFailed as exc:
        _record_completion(repo, task, receipt, assessment, expected_tree)
        _complete_task(repo, task, active_stage, branch, target)
        exc.lines.extend([f"TASK: {task}", "STATUS: completed-locally"])
        raise
    except Blocked as exc:
        exc.lines.extend(
            [
                f"TASK: {task}",
                f"STATUS: {active_stage}",
                "RECOVERY: receipt and task branch retained; integration target unchanged",
                f"NEXT: inspect with 'invariant task status {task}', correct the candidate or "
                "assessment, then rerun task finish",
            ]
        )
        raise
    _record_completion(repo, task, receipt, assessment, expected_tree)
    _complete_task(repo, task, active_stage, branch, target)
    return [*output, f"TASK: {task}", "STATUS: completed"]


def prepare_assessment(repo: Path, task: str) -> tuple[dict[str, object], dict[str, object]]:
    """Compile a candidate-bound assessment draft and its remaining semantic requirements."""
    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    if stage not in {"implementing", "implementing-unborn", "awaiting-review"}:
        raise Blocked(f"Invariant: task '{task}' has no candidate to assess (stage '{stage}')")
    active_stage = (
        "implementing-unborn"
        if str(receipt.get("integration_head")) == "unborn"
        else "implementing"
    )
    branch = str(lifecycle.get("branch") or "")
    target = str(receipt.get("integration_target") or "")
    base = str(receipt.get("integration_head") or "")
    _, paths = _actual_paths(repo, active_stage, base, branch)
    if not paths:
        raise Blocked("Invariant: task candidate contains no changes")
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
    interfaces = sorted({str(item) for item in scope.get("interfaces", [])})
    selected_domains = {str(item) for item in scope.get("domains", [])}
    candidate_repo = _candidate_repo(repo, active_stage, branch)

    def changed_records(
        relative: str, current: list[dict[str, object]], previous: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        if relative not in paths:
            return []
        before = {str(row.get("id")): row for row in previous if row.get("id")}
        return [row for row in current if row.get("id") and before.get(str(row["id"])) != row]

    previous_ref = None if active_stage == "implementing-unborn" else base
    changed_domains = changed_records(
        ".invariant/DOMAINS.yml",
        governance.domains(candidate_repo),
        governance.domains(candidate_repo, previous_ref) if previous_ref else [],
    )
    changed_contracts = changed_records(
        ".invariant/CONTRACTS.yml",
        governance.contracts(candidate_repo),
        governance.contracts(candidate_repo, previous_ref) if previous_ref else [],
    )
    changed_constraints = changed_records(
        ".invariant/CONSTRAINTS.yml",
        governance.constraints(candidate_repo),
        governance.constraints(candidate_repo, previous_ref) if previous_ref else [],
    )
    previous_semantics = {
        row.identifier: row
        for row in (governance.semantic_records(candidate_repo, previous_ref) if previous_ref else [])
    }
    changed_semantics = (
        [
            row
            for row in governance.semantic_records(candidate_repo)
            if previous_semantics.get(row.identifier) != row
        ]
        if ".invariant/SEMANTICS.yml" in paths
        else []
    )
    selected_domains.update(str(row["id"]) for row in changed_domains)
    for row in changed_contracts:
        selected_domains.update(governance.refs(row.get("between")))
    for row in changed_constraints:
        selected_domains.update(governance.refs(row.get("applies_to")))
    domains = sorted(selected_domains)
    reach_lines = governance.reach(
        candidate_repo,
        paths=paths,
        base=previous_ref,
        root_mode=active_stage == "implementing-unborn",
        domains_selected=domains,
        interfaces=interfaces,
    )
    reach = next(
        (line.removeprefix("REACH: ") for line in reach_lines if line.startswith("REACH: ")),
        "local",
    )
    verifier_lines = governance.verifiers(
        candidate_repo,
        paths=paths,
        base=previous_ref,
        root_mode=active_stage == "implementing-unborn",
        domains_selected=domains,
        interfaces=interfaces,
    )
    reviews = sorted(
        {
            line.split(" ", 2)[1]
            for line in verifier_lines
            if line.startswith("REVIEW: ")
        }
    )
    changed_architecture = [
        reference
        for reference in reviews
        if reference.startswith("architecture:")
        and reference.removeprefix("architecture:").split("#", 1)[0] in paths
    ]
    will_run = sorted(
        {
            line.split(" ", 2)[2]
            for line in verifier_lines
            if line.startswith("VERIFY: ")
        }
    )
    governance_refs = [
        *[f"semantic:{row.identifier}" for row in changed_semantics],
        *[f"domain:{row['id']}" for row in changed_domains],
        *[f"contract:{row['id']}" for row in changed_contracts],
        *[f"constraint:{row['id']}" for row in changed_constraints],
        *changed_architecture,
    ]
    durable_registry_changed = bool(
        {
            ".invariant/SEMANTICS.yml",
            ".invariant/DOMAINS.yml",
            ".invariant/CONTRACTS.yml",
            ".invariant/CONSTRAINTS.yml",
        }
        .intersection(paths)
    )
    change_classification = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    boundary = str(change_classification.get("boundary") or "unresolved")
    if boundary == "unresolved":
        if governance_refs or durable_registry_changed:
            boundary = "recorded"
        elif reach in {"local", "bounded"}:
            boundary = "no-record"
    resolved = _target_config(repo, target)
    accepted_authority = (
        resolved.authority
        if base == "unborn"
        else config.resolve_at(repo, base, target).authority
    )
    agent_authority = resolved.authority == "agent" and accepted_authority == "agent"
    allow_open = reach in {"open", "gated"} and agent_authority and boundary != "unresolved"
    candidate_tree = landing.prospective_tree(
        repo, target, None if active_stage == "implementing-unborn" else branch
    )
    assessment: dict[str, object] = {
        "version": 1,
        "goal_digest": str(receipt.get("goal_digest") or ""),
        "paths": paths,
        "interfaces": interfaces,
        "domains": domains,
        "boundary": {"disposition": boundary},
        "governance": sorted(governance_refs),
        "architecture_reviews": [],
        "checks": [],
        "allow_open": allow_open,
    }
    required: list[dict[str, object]] = []
    if boundary == "unresolved":
        required.append(
            {
                "field": "boundary.disposition",
                "reason": "open reach needs a durable-meaning decision",
                "allowed": ["no-record", "recorded", "audit:<id>"],
            }
        )
    if boundary == "recorded" and not governance_refs:
        required.append(
            {
                "field": "governance",
                "reason": "the candidate changes durable governance but no surviving candidate record can be inferred",
                "allowed": ["semantic:<id>", "domain:<id>", "contract:<id>", "constraint:<id>", "architecture:<path>#<anchor>"],
            }
        )
    if reviews:
        required.append(
            {
                "field": "architecture_reviews",
                "reason": "the final candidate review must acknowledge these affected decisions",
                "values": reviews,
            }
        )
    if reach in {"open", "gated"} and not allow_open:
        required.append(
            {
                "field": "allow_open",
                "reason": "human semantic authority must approve this open or gated transition",
                "value_after_approval": True,
            }
        )
    analysis: dict[str, object] = {
        "candidate_tree": candidate_tree,
        "adapters": [],
        "reach": reach,
        "inferred": {
            "paths": paths,
            "interfaces": interfaces,
            "domains": domains,
            "governance": sorted(governance_refs),
        },
        "required": required,
        "recommended_architecture_reviews": reviews,
        "will_run": will_run,
        "reach_records": reach_lines,
    }
    return assessment, analysis


def _request_packet(
    repo: Path,
    task: str,
    assessment: dict[str, object],
    analysis: dict[str, object],
    evidence: list[dict[str, object]],
    retained_discoveries: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    packet_body: dict[str, object] = {
        "version": 1,
        "task": task,
        "goal_digest": assessment["goal_digest"],
        "candidate_tree": analysis["candidate_tree"],
        "reach": analysis["reach"],
        "changed_paths": assessment["paths"],
        "affected_semantics": analysis["recommended_architecture_reviews"],
        "governance": assessment["governance"],
        "will_run": analysis["will_run"],
        "evidence_ids": [
            str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")
        ],
        "retained_discoveries": retained_discoveries,
    }
    review_id = git.hash_text(repo, repr(packet_body))
    packet = {**packet_body, "review_id": review_id}
    request = {
        "id": "core:candidate-review",
        "adapter": "core",
        "phase": CANDIDATE_EVIDENCED,
        "kind": "review_semantics",
        "prompt": (
            "Review the exact candidate against the affected canonical prose. Return one "
            "semantic effect and attributable summary. Candidate defects block acceptance; "
            "discoveries deliberately retained in the audit are non-blocking references. "
            "Set review_mode to independent only when the host actually routed this action "
            "away from the candidate author."
        ),
        "input_schema": candidate_review_schema(),
        "schema_id": "invariant://schemas/actions/review-semantics/v1",
        "blocking": True,
        "context": packet,
    }
    return packet, request


def _land_request_from_assessment(
    repo: Path,
    task: str,
    assessment: dict[str, object],
) -> landing.LandRequest:
    receipt = receipts.load(repo, task)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    active_stage = (
        "implementing-unborn"
        if str(receipt.get("integration_head")) == "unborn"
        else "implementing"
    )
    branch = str(lifecycle.get("branch") or "")
    boundary = assessment.get("boundary") if isinstance(assessment.get("boundary"), dict) else {}
    disposition = str(boundary.get("disposition") or "no-record")
    if disposition == "unresolved":
        disposition = "no-record"
    paths = assessment.get("paths", []) if isinstance(assessment.get("paths"), list) else []
    return landing.LandRequest(
        mode="direct" if active_stage == "implementing-unborn" else "merge",
        merge_branch=None if active_stage == "implementing-unborn" else branch,
        subject=f"Invariant task {task}",
        units=(task,),
        scopes=("area.root",),
        paths=tuple(str(item) for item in paths) if active_stage == "implementing-unborn" else (),
        domains=tuple(str(item) for item in assessment.get("domains", [])),
        interfaces=tuple(str(item) for item in assessment.get("interfaces", [])),
        governance_refs=tuple(str(item) for item in assessment.get("governance", [])),
        reviewed=tuple(str(item) for item in assessment.get("architecture_reviews", [])),
        boundary=disposition,
        checks=tuple(str(item) for item in assessment.get("checks", [])),
        target=str(receipt.get("integration_target") or ""),
        allow_open=bool(assessment.get("allow_open", False)),
    )


def prepare_finish(
    repo: Path,
    task: str,
    *,
    subject: str | None = None,
    checks: Iterable[str] = (),
) -> FlowResult:
    """Collect evidence, expose semantic hook actions, or complete a routine task."""

    assessment, analysis = prepare_assessment(repo, task)
    assessment["checks"] = sorted(
        set([*assessment.get("checks", []), *[str(item) for item in checks]])
    )
    local = receipts.task_root(repo, task)
    local.mkdir(parents=True, exist_ok=True)
    prepared = local / "prepared-assessment.yml"
    dump_yaml(prepared, assessment)
    evidence_request = _land_request_from_assessment(repo, task, assessment)
    if subject:
        evidence_request = landing.LandRequest(
            **{**evidence_request.__dict__, "subject": subject}
        )
    candidate, _, evidence = landing.collect_evidence(repo, evidence_request)
    analysis["candidate_tree"] = candidate.tree
    evidence_root = local / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for item in evidence:
        identifier = str(item.get("evidence_id") or git.hash_text(repo, repr(item)))
        dump_yaml(evidence_root / f"{identifier.replace(':', '-')}.yml", item)

    evidence_ids = [
        str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")
    ]

    receipt = receipts.load(repo, task)
    receipt["finish_subject"] = subject or f"Invariant task {task}"
    receipt["review_candidate_tree"] = candidate.tree
    receipt["candidate_evidence_ids"] = evidence_ids
    retained_discoveries = _retained_discoveries(receipt)
    adapters.run_hook(
        local,
        receipt,
        CANDIDATE_EVIDENCED,
        candidate_tree=candidate.tree,
        evidence=tuple(evidence),
        retained_discoveries=tuple(retained_discoveries),
    )
    requests = adapters.pending(receipt)
    semantic_required = bool(analysis.get("required"))
    if semantic_required:
        packet, core_request = _request_packet(
            repo,
            task,
            assessment,
            analysis,
            evidence,
            retained_discoveries,
        )
        dump_yaml(local / "review-packet.yml", packet)
        requests.append(core_request)
    receipt["hook_requests"] = requests
    receipt["assurance"] = _assurance_summary(evidence, requests)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    if requests:
        receipt = _transition(
            receipt,
            "awaiting-review",
            str(lifecycle.get("branch") or ""),
            str(lifecycle.get("worktree") or repo),
        )
        receipts.save(repo, task, receipt)
        lines = [
            f"ASSESSMENT: inferred {task}",
            f"TASK: {task}",
            "STATUS: awaiting-review",
            f"CANDIDATE-TREE: {candidate.tree}",
            *_assurance_lines(receipt.get("assurance")),
            *_hook_lines(receipt),
            f"EVIDENCE: {len(evidence_ids)} retained — invariant task evidence {task}",
        ]
        return FlowResult(
            lines,
            {
                "task": task,
                "stage": "awaiting-review",
                "candidate_tree": candidate.tree,
                "actions": adapters.action_descriptors(receipt),
                "evidence_ids": evidence_ids,
                "assurance": receipt["assurance"],
            },
            "needs_input",
        )
    receipts.save(repo, task, receipt)
    assurance = receipt.get("assurance", {})
    finish(
        repo,
        task,
        assessment_path=str(prepared),
        subject=subject,
    )
    return FlowResult(
        [
            f"ASSESSMENT: inferred {task}",
            *_completion_delta_lines(
                repo,
                task,
                candidate_tree=candidate.tree,
                evidence_count=len(evidence_ids),
            ),
        ],
        {
            "task": task,
            "stage": "completed",
            "actions": [],
            "candidate_tree": candidate.tree,
            "evidence_ids": evidence_ids,
            "assurance": assurance,
        },
    )


def _apply_core_review(
    repo: Path,
    task: str,
    request: dict[str, object],
    source: str,
) -> CandidateReview:
    review = CandidateReview.load(source)
    context = request.get("context") if isinstance(request.get("context"), dict) else {}
    if (
        review.review_id != context.get("review_id")
        or review.candidate_tree != context.get("candidate_tree")
    ):
        raise Blocked(
            "Invariant: candidate review is stale for the current review packet",
            code="stale_candidate_review",
        )
    if review.verdict != "accepted" or review.candidate_defects:
        raise Blocked(
            "Invariant: candidate review must accept the candidate without unresolved candidate defects",
            code="candidate_not_accepted",
        )
    allowed_discoveries = {
        str(item)
        for item in context.get("retained_discoveries", [])
        if isinstance(item, str)
    }
    unknown_discoveries = sorted(set(review.retained_discoveries) - allowed_discoveries)
    if unknown_discoveries:
        raise Blocked(
            f"Invariant: candidate review references unknown retained discovery '{unknown_discoveries[0]}'",
            code="invalid_review_discovery",
        )
    resolved = config.resolve(repo)
    if resolved.authority == "human" and not review.authority.startswith("user:"):
        raise Blocked(
            "Invariant: human semantic authority requires an attributable user: locator",
            code="authority_required",
        )
    local = receipts.task_root(repo, task)
    assessment_path = local / "prepared-assessment.yml"
    raw = load_yaml(assessment_path)
    if not isinstance(raw, dict):
        raise InvariantError("Invariant: prepared assessment is missing")
    inferred = raw.get("boundary") if isinstance(raw.get("boundary"), dict) else {}
    if inferred.get("disposition") == "recorded" and review.semantic_effect != "recorded":
        raise Blocked(
            "Invariant: candidate changes durable records and must be reviewed as recorded",
            code="invalid_boundary",
        )
    if review.semantic_effect == "recorded" and not raw.get("governance"):
        raise Blocked(
            "Invariant: recorded semantic effect requires a surviving semantic record",
            code="invalid_boundary",
        )
    raw["boundary"] = {"disposition": review.semantic_effect}
    raw["architecture_reviews"] = list(context.get("affected_semantics", []))
    raw["allow_open"] = True
    raw["prose"] = review.summary
    dump_yaml(local / "accepted-assessment.yml", raw)
    shutil.copyfile(source, local / "candidate-review.yml")
    return review


def _assessment_for_completion(repo: Path, task: str) -> Path:
    local = receipts.task_root(repo, task)
    accepted = local / "accepted-assessment.yml"
    return accepted if accepted.is_file() else local / "prepared-assessment.yml"


def continue_task(repo: Path, task: str, *, apply: bool = False) -> list[str]:
    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    branch = str(lifecycle.get("branch") or "")
    target = str(receipt.get("integration_target") or "")
    if stage in {"implementing", "implementing-unborn"}:
        return _status_lines(repo, receipt)
    if stage not in {"awaiting-branch", "awaiting-landing"}:
        raise Blocked(f"Invariant: task '{task}' cannot continue from stage '{stage or 'unknown'}")
    if not apply:
        action = (
            f"create a linked worktree for {branch} from {target}"
            if stage == "awaiting-branch"
            else f"verify the exact candidate and atomically land it onto {target}"
        )
        raise Blocked(
            "Invariant: continuation requires --apply",
            code="lifecycle_paused",
            lines=[f"TASK: {task}", f"STATUS: {stage}", f"PROPOSED: {action}"],
        )
    if stage == "awaiting-branch":
        receipts.check_receipt(repo, task, goal_digest=str(receipt.get("goal_digest")))
        worktree = _create_branch(repo, branch, target)
        next_stage = "briefing" if _blocking_hook_requests(receipt) else "implementing"
        receipt = receipts.set_lifecycle(repo, task, next_stage, branch, str(worktree))
        return [*_status_lines(repo, receipt), *_hook_lines(receipt)]
    local = receipts.task_root(repo, task)
    pending_assessment = local / "pending-assessment.yml"
    pending = load_yaml(local / "pending-finish.yml")
    if not pending_assessment.is_file() or not isinstance(pending, dict):
        raise InvariantError(f"Invariant: task '{task}' has incomplete pending landing state")
    active_stage = (
        "implementing-unborn"
        if str(receipt.get("integration_head")) == "unborn"
        else "implementing"
    )
    receipts.set_lifecycle(
        repo,
        task,
        active_stage,
        branch,
        str(lifecycle.get("worktree") or repo),
    )
    return finish(
        repo,
        task,
        assessment_path=str(pending_assessment),
        subject=str(pending.get("subject") or f"Invariant task {task}"),
        checks=[str(item) for item in pending.get("checks", [])],
        continuation_apply=True,
    )


def task_guidance(repo: Path, task: str, *, full: bool = False) -> list[str]:
    receipt = receipts.load(repo, task)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
    change_classification = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    domains = [str(item) for item in scope.get("domains", [])]
    initial_paths = [str(item) for item in scope.get("paths", [])]
    interfaces = [str(item) for item in scope.get("interfaces", [])]
    captured_head = str(receipt.get("integration_head") or "")
    stage = str(lifecycle.get("stage") or "briefed")
    branch = str(lifecycle.get("branch") or "")
    candidate_paths: list[str] = []
    if stage == "implementing" and branch and captured_head not in {"", "unborn"}:
        branch_ref = git.resolve(repo, f"refs/heads/{branch}")
        if branch_ref:
            candidate_paths.extend(git.changed_paths(repo, captured_head, branch_ref))
        worktree = git.worktree_for_branch(repo, branch)
        if worktree:
            candidate_paths.extend(git.changed_paths(worktree))
    elif stage == "implementing-unborn":
        candidate_paths.extend(git.changed_paths(repo))
    candidate_paths = sorted(set(candidate_paths))
    paths = candidate_paths or initial_paths
    path_basis = "current candidate" if candidate_paths else "initial scope"
    accepted_at = None if captured_head in {"", "unborn"} else captured_head
    output = [
        "# Active task context",
        "",
        f"Task: {task}",
        f"Stage: {stage}",
        f"Boundary: {change_classification.get('boundary') or 'unknown'}",
        f"Accepted ground: {captured_head or 'unknown'}",
        f"Paths ({path_basis}): {_path_summary(paths)}",
        f"Interfaces: {', '.join(interfaces) or 'none selected'}",
        f"Domains: {', '.join(domains) or 'none selected'}",
    ]
    adapter_context = adapters.context(receipts.task_root(repo, task), receipt)
    if adapter_context:
        output.extend(["", *adapter_context])
    rows = governance.display_rows(repo, domains, accepted_at)
    if domains:
        output.extend(["", "# Selected durable governance", "", *rows])
    architecture = governance.architecture_context(
        repo,
        domains,
        accepted_at,
        paths=paths,
        interfaces=interfaces,
    )
    if architecture:
        output.extend(["", "# Selected architecture prose", "", *architecture])
    discoveries = governance.discovery_context(repo, paths, domains)
    if discoveries:
        output.extend(["", "# Relevant discoveries", "", *discoveries])
    output.extend(
        [
            "",
            *guidance.for_stage(
                str(lifecycle.get("stage") or "briefed"), full=full
            ).splitlines(),
        ]
    )
    adapter_phase = (
        TASK_CREATED
        if stage in {"briefing", "awaiting-branch"}
        else CANDIDATE_EVIDENCED
        if stage == "awaiting-review"
        else stage
    )
    adapter_guidance = adapters.guidance(receipt, adapter_phase)
    if adapter_guidance:
        output.extend(["", *adapter_guidance])
    return output


def _path_summary(paths: list[str], limit: int = 12) -> str:
    if not paths:
        return "none selected"
    visible = paths[:limit]
    remainder = len(paths) - len(visible)
    suffix = f" (+{remainder} more)" if remainder else ""
    return f"{', '.join(visible)}{suffix}"


def invalidate(repo: Path, task: str) -> list[str]:
    return receipts.invalidate(repo, task)
