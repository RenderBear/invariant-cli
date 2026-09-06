from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Iterable, Mapping

from invariant import adapters
from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.mechanics import config, coordinate, git, governance, landing, receipts
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.semantics import guidance
from invariant.semantics.models import Assessment


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


def _raise_adapter_gate(repo: Path, task: str, receipt: dict[str, object], gate) -> None:
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    branch = str(lifecycle.get("branch") or "")
    worktree = str(lifecycle.get("worktree") or repo)
    receipts.set_lifecycle(repo, task, gate.stage, branch, worktree)
    raise Blocked(
        gate.message,
        code=gate.code,
        lines=[
            f"TASK: {task}",
            f"STATUS: {gate.stage}",
            *gate.lines,
            f"GUIDANCE: invariant task guidance {task}",
        ],
    )


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
        lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
        stage = str(lifecycle.get("stage") or "")
        gate = adapters.begin(
            receipts.task_root(repo, task),
            receipt,
            adapter_inputs or {},
        )
        receipts.save(repo, task, receipt)
        if gate:
            _raise_adapter_gate(repo, task, receipt, gate)
        if adapters.is_begin_stage(receipt, stage):
            return _activate(repo, task, receipt, execution=_target_config(repo, str(receipt["integration_target"])).execution)
        return _status_lines(repo, receipt)

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
    if adapter_ids:
        receipt = receipts.set_lifecycle(
            repo, task, adapters.begin_stage(adapter_ids), "", str(repo)
        )
    receipt["adapter_digest"] = adapters.digest(adapter_ids)
    # Persist the selected adapter protocol before parsing host input so invalid
    # input remains recoverable through the same task receipt.
    receipts.save(repo, task, receipt)
    gate = adapters.begin(
        receipts.task_root(repo, task),
        receipt,
        adapter_inputs or {},
    )
    receipts.save(repo, task, receipt)
    if gate:
        _raise_adapter_gate(repo, task, receipt, gate)
    return _activate(repo, task, receipt, execution=resolved.execution)


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
        f"LIFECYCLE-ROOT: {git.primary_worktree(repo)}",
        f"RECEIPT: {receipts.receipt_path(repo, str(receipt.get('task')))}",
        f"ADAPTERS: {', '.join(adapter_ids) or 'none'}",
    ]
    adapter_root = receipts.task_root(repo, str(receipt.get("task"))) / "adapters"
    if adapter_root.is_dir():
        output.append(f"ADAPTER-STATE: {adapter_root}")
    return output


def status(repo: Path, task: str) -> list[str]:
    if not git.valid_id(task):
        raise InvariantError(f"Invariant: invalid task id '{task}'")
    path = receipts.receipt_path(repo, task)
    if not path.is_file():
        raise Blocked(f"TASK: {task}\nSTATUS: absent", code="missing_task")
    return _status_lines(repo, receipts.load(repo, task))


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
            lines=[f"LIFECYCLE-ROOT: {primary}", f"NEXT: run invariant task finish from {primary}"],
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
    receipts.invalidate(repo, task)


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
    adapter_gate = adapters.gate_for_stage(receipt, stage)
    if stage not in {"implementing", "implementing-unborn"} and not adapters.is_review_stage(receipt, stage):
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
    expected_tree = None
    if adapters.enabled(receipt):
        candidate_tree = landing.prospective_tree(repo, target, None if active_stage == "implementing-unborn" else branch)
        gate = adapters.review_candidate(
            receipts.task_root(repo, task),
            receipt,
            candidate_tree,
            adapter_inputs or {},
        )
        if gate:
            _raise_adapter_gate(repo, task, receipt, gate)
        if adapter_gate:
            receipts.set_lifecycle(
                repo,
                task,
                active_stage,
                branch,
                str(lifecycle.get("worktree") or repo),
            )
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
        receipts.set_lifecycle(
            repo,
            task,
            "awaiting-landing",
            branch,
            str(lifecycle.get("worktree") or repo),
        )
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
    _complete_task(repo, task, active_stage, branch, target)
    return [*output, f"TASK: {task}", "STATUS: completed"]


def prepare_assessment(repo: Path, task: str) -> tuple[dict[str, object], dict[str, object]]:
    """Compile a candidate-bound assessment draft and its remaining semantic requirements."""
    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    adapter_gate = adapters.gate_for_stage(receipt, stage)
    if stage not in {"implementing", "implementing-unborn"} and not adapters.is_review_stage(receipt, stage):
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
        *[f"domain:{row['id']}" for row in changed_domains],
        *[f"contract:{row['id']}" for row in changed_contracts],
        *[f"constraint:{row['id']}" for row in changed_constraints],
        *changed_architecture,
    ]
    durable_registry_changed = bool(
        {".invariant/DOMAINS.yml", ".invariant/CONTRACTS.yml", ".invariant/CONSTRAINTS.yml"}
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
    adapter_analysis = adapters.prepare_candidate(
        receipts.task_root(repo, task), receipt, candidate_tree
    )
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
                "allowed": ["domain:<id>", "contract:<id>", "constraint:<id>", "architecture:<path>#<anchor>"],
            }
        )
    if reviews:
        required.append(
            {
                "field": "architecture_reviews",
                "reason": "review these affected decisions before copying their locators into the assessment",
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
        "adapters": adapter_analysis,
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


def continue_task(repo: Path, task: str, *, apply: bool = False) -> list[str]:
    receipt = receipts.load(repo, task)
    _validate_adapter_receipt(receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    branch = str(lifecycle.get("branch") or "")
    target = str(receipt.get("integration_target") or "")
    if stage in {"implementing", "implementing-unborn"}:
        return _status_lines(repo, receipt)
    adapter_gate = adapters.gate_for_stage(receipt, stage)
    if adapter_gate:
        raise Blocked(adapter_gate.message, code=adapter_gate.code, lines=list(adapter_gate.lines))
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
        receipt = receipts.set_lifecycle(repo, task, "implementing", branch, str(worktree))
        return _status_lines(repo, receipt)
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


def task_guidance(repo: Path, task: str) -> list[str]:
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
        f"Paths ({path_basis}): {', '.join(paths) or 'none selected'}",
        f"Interfaces: {', '.join(interfaces) or 'none selected'}",
        f"Domains: {', '.join(domains) or 'none selected'}",
    ]
    adapter_context = adapters.context(receipts.task_root(repo, task), receipt)
    if adapter_context:
        output.extend(["", *adapter_context])
    rows = governance.display_rows(repo, domains, accepted_at)
    if domains:
        output.extend(["", "# Selected durable governance", "", *rows])
    architecture = governance.architecture_context(repo, domains, accepted_at)
    if architecture:
        output.extend(["", "# Selected architecture prose", "", *architecture])
    discoveries = governance.discovery_context(repo, paths, domains)
    if discoveries:
        output.extend(["", "# Relevant discoveries", "", *discoveries])
    output.extend(
        [
            "",
            *guidance.for_stage(str(lifecycle.get("stage") or "briefed")).splitlines(),
        ]
    )
    adapter_guidance = adapters.guidance(receipt, stage)
    if adapter_guidance:
        output.extend(["", *adapter_guidance])
    return output


def invalidate(repo: Path, task: str) -> list[str]:
    return receipts.invalidate(repo, task)
