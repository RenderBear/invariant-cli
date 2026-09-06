from __future__ import annotations

import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

import yaml

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import config, git, governance
from invariant.mechanics.documents import dump_yaml, load_yaml


def receipt_root(repo: Path) -> Path:
    return git.common_dir(repo) / "invariant" / "briefs"


def task_root(repo: Path, task: str) -> Path:
    return git.common_dir(repo) / "invariant" / "tasks" / task


def receipt_path(repo: Path, task: str) -> Path:
    return receipt_root(repo) / f"{task}.yml"


def mechanics_digest() -> str:
    package = Path(__file__).resolve().parents[1]
    digest = sha256()
    # Receipt reuse depends only on the code that resolves configuration,
    # repository identity, selected governance, material change, and receipt
    # compatibility. Landing, coordination, presentation, and prose guidance
    # are independently recomputed or reloaded and must not evict this cache.
    dependencies = (
        "mechanics/config.py",
        "mechanics/documents.py",
        "mechanics/git.py",
        "mechanics/governance.py",
        "mechanics/receipts.py",
    )
    for relative in dependencies:
        path = package / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def repository_identity(repo: Path, target: str) -> str:
    roots = git.run(["rev-list", "--max-parents=0", f"refs/heads/{target}"], cwd=repo, check=False).stdout
    source = "\n".join(sorted(roots.splitlines())) + ("\n" if roots else str(git.common_dir(repo)) + "\n")
    return git.hash_text(repo, source)


def integration_head(repo: Path, target: str) -> str:
    return git.resolve(repo, f"refs/heads/{target}") or "unborn"


def load(repo: Path, task: str) -> dict[str, Any]:
    path = receipt_path(repo, task)
    if not path.is_file():
        raise Blocked(f"Invariant: no active task '{task}'", code="missing_task")
    raw = load_yaml(path)
    if not isinstance(raw, dict) or raw.get("version") != 1 or raw.get("task") != task:
        raise InvariantError(f"Invariant: corrupt cached brief '{task}'", code="corrupt_receipt")
    return raw


def completed_task_root(repo: Path, task: str) -> Path | None:
    root = git.common_dir(repo) / "invariant" / "history" / "tasks" / task
    if not root.is_dir():
        return None
    candidates = list(root.glob("*/receipt.yml"))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.stat().st_mtime_ns).parent


def load_completed(repo: Path, task: str) -> dict[str, Any] | None:
    """Load the most recently archived completion for a reusable task id."""

    root = completed_task_root(repo, task)
    if root is None:
        return None
    path = root / "receipt.yml"
    raw = load_yaml(path)
    if not isinstance(raw, dict) or raw.get("version") != 1 or raw.get("task") != task:
        raise InvariantError(
            f"Invariant: corrupt completed task archive '{task}'",
            code="corrupt_receipt",
        )
    return raw


def save(repo: Path, task: str, receipt: dict[str, Any]) -> None:
    dump_yaml(receipt_path(repo, task), receipt)


def open_receipt(
    repo: Path,
    task: str,
    *,
    goal: str,
    boundary: str,
    posture: str | None = None,
    paths: Iterable[str] = (),
    interfaces: Iterable[str] = (),
    domains: Iterable[str] = (),
    adapters: Iterable[str] = (),
) -> tuple[dict[str, Any], list[str]]:
    resolved = config.resolve(repo)
    target = resolved.integration_branch
    head = integration_head(repo, target)
    selected = sorted(set(domains))
    selected_paths = sorted(set(paths))
    selected_interfaces = sorted(set(interfaces))
    governance_snapshot = {
        "selected_digest": governance.context_digest(
            repo, selected, selected_paths, selected_interfaces
        ),
        "integration_digest": (
            governance.context_digest(
                repo, selected, selected_paths, selected_interfaces, head
            )
            if head != "unborn"
            else git.hash_text(repo, "")
        ),
    }
    change_classification = {
        "boundary": boundary,
    }
    if posture:
        change_classification["posture"] = posture
    adapter_ids = sorted(set(adapters))
    receipt = {
        "version": 1,
        "repository": repository_identity(repo, target),
        "task": task,
        "goal_digest": git.hash_text(repo, goal),
        "integration_target": target,
        "integration_head": head,
        "mechanics_digest": mechanics_digest(),
        "scope": {
            "paths": selected_paths,
            "interfaces": selected_interfaces,
            "domains": selected,
        },
        "governance_snapshot": governance_snapshot,
        "change_classification": change_classification,
        "adapters": adapter_ids,
    }
    if adapter_ids:
        receipt["goal"] = goal
    save(repo, task, receipt)
    return receipt, [f"BRIEF: opened {task}", f"RECEIPT: {receipt_path(repo, task)}"]


def _scope(receipt: dict[str, Any], name: str) -> list[str]:
    scope = receipt.get("scope")
    if not isinstance(scope, dict):
        return []
    value = scope.get(name)
    return [str(item) for item in value] if isinstance(value, list) else []


def check_receipt(
    repo: Path,
    task: str,
    *,
    goal: str | None = None,
    goal_digest: str | None = None,
    compatible_goal: bool = False,
    paths: Iterable[str] | None = None,
    interfaces: Iterable[str] | None = None,
    domains: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    receipt = load(repo, task)
    captured_target = str(receipt.get("integration_target", ""))
    previous = os.environ.get("INVARIANT_INTEGRATION_TARGET")
    os.environ["INVARIANT_INTEGRATION_TARGET"] = captured_target
    try:
        target = config.resolve(repo).integration_branch
    finally:
        if previous is None:
            os.environ.pop("INVARIANT_INTEGRATION_TARGET", None)
        else:
            os.environ["INVARIANT_INTEGRATION_TARGET"] = previous
    if target != captured_target:
        raise Blocked(
            f"STALE: integration target changed from {captured_target} to {target}", code="stale_receipt"
        )
    if repository_identity(repo, target) != receipt.get("repository"):
        raise Blocked("STALE: repository identity changed", code="stale_receipt")
    if mechanics_digest() != receipt.get("mechanics_digest"):
        raise Blocked("STALE: CLI mechanics changed", code="stale_receipt")
    selected = _scope(receipt, "domains")
    selected_paths = _scope(receipt, "paths")
    selected_interfaces = _scope(receipt, "interfaces")
    governance_snapshot = (
        receipt.get("governance_snapshot")
        if isinstance(receipt.get("governance_snapshot"), dict)
        else {}
    )
    change_classification = (
        receipt.get("change_classification")
        if isinstance(receipt.get("change_classification"), dict)
        else {}
    )
    if governance.context_digest(
        repo, selected, selected_paths, selected_interfaces
    ) != governance_snapshot.get("selected_digest"):
        raise Blocked("STALE: selected governance changed", code="stale_receipt")

    if (goal is None) == (goal_digest is None):
        raise InvariantError("Invariant: supply exactly one of goal or goal digest")
    current_goal = git.hash_text(repo, goal) if goal is not None else str(goal_digest)
    if not re_full_hex(current_goal):
        raise InvariantError(f"Invariant: invalid goal digest '{current_goal}'")
    goal_changed = current_goal != receipt.get("goal_digest")
    if goal_changed and not (goal is not None and compatible_goal):
        raise Blocked("STALE: goal changed", code="stale_receipt")

    requested = {"paths": paths, "interfaces": interfaces, "domains": domains}
    labels = {"paths": "path", "interfaces": "interface", "domains": "domain"}
    for name, values in requested.items():
        if values is None:
            continue
        cached = set(_scope(receipt, name))
        for item in sorted(set(values)):
            if item not in cached:
                raise Blocked(f"STALE: {labels[name]} scope expanded to {item}", code="stale_receipt")

    cached_head = str(receipt.get("integration_head"))
    current_head = integration_head(repo, target)
    head_advanced = current_head != cached_head
    integration_digest = governance_snapshot.get("integration_digest")
    if head_advanced:
        if "unborn" in {cached_head, current_head}:
            raise Blocked("STALE: integration branch birth state changed", code="stale_receipt")
        if not git.is_ancestor(repo, cached_head, current_head):
            raise Blocked(
                "STALE: integration history no longer descends from the cached head", code="stale_receipt"
            )
        integration_digest = governance.context_digest(
            repo,
            selected,
            selected_paths,
            selected_interfaces,
            current_head,
        )
        if integration_digest != governance_snapshot.get("integration_digest"):
            raise Blocked(
                "STALE: selected governance changed on the integration branch", code="stale_receipt"
            )
        material = governance.material_changes(repo, cached_head, current_head, selected)
        if material:
            locator = material[0].removeprefix("MATERIAL-CHANGED: ")
            raise Blocked(f"STALE: governing material changed — {locator}", code="stale_receipt")
        task_tip = git.resolve(repo, "HEAD")
        if task_tip and task_tip != current_head:
            if not git.is_ancestor(repo, cached_head, task_tip):
                raise Blocked(
                    "STALE: task history no longer descends from the cached head", code="stale_receipt"
                )
            try:
                git.merge_tree(repo, current_head, task_tip)
            except Blocked as exc:
                raise Blocked(
                    f"MERGE-REQUIRED: task conflicts with advanced integration head {current_head}",
                    code="merge_conflict",
                    lines=exc.lines,
                ) from exc

    if head_advanced or goal_changed:
        receipt["integration_head"] = current_head
        receipt["goal_digest"] = current_goal
        governance_snapshot["integration_digest"] = integration_digest
        receipt["governance_snapshot"] = governance_snapshot
        save(repo, task, receipt)
    output: list[str] = []
    if head_advanced:
        output.append(f"HEAD: advanced {cached_head}..{current_head} — mergeable, brief reused")
    if goal_changed:
        output.append("GOAL: changed text accepted for cached semantic envelope")
    output.extend([f"BRIEF: fresh {task}", "REUSE: cached semantic envelope"])
    if change_classification.get("posture"):
        output.append(f"POSTURE: {change_classification['posture']}")
    output.append(f"BOUNDARY: {change_classification.get('boundary', '')}")
    return receipt, output


def re_full_hex(value: str) -> bool:
    return bool(value) and all(character in "0123456789abcdef" for character in value)


def set_lifecycle(repo: Path, task: str, stage: str, branch: str, worktree: str) -> dict[str, Any]:
    receipt = load(repo, task)
    receipt["lifecycle"] = {"stage": stage, "branch": branch, "worktree": worktree}
    save(repo, task, receipt)
    return receipt


def invalidate(repo: Path, task: str) -> list[str]:
    path = receipt_path(repo, task)
    existed = path.is_file()
    if existed:
        path.unlink()
    local_task = task_root(repo, task)
    if local_task.is_dir():
        shutil.rmtree(local_task)
    return [f"BRIEF: invalidated {task}" if existed else f"BRIEF: absent {task}"]


def complete(repo: Path, task: str, landed_commit: str) -> Path:
    """Archive the task's semantic argument trail after successful local landing."""

    receipt = load(repo, task)
    receipt["completed_commit"] = landed_commit
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    receipt["lifecycle"] = {**lifecycle, "stage": "completed"}
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
    coverage = (
        governance_run.get("coverage")
        if isinstance(governance_run.get("coverage"), dict)
        else {}
    )
    selected_findings = governance_run.get("selected_findings", [])
    projected_records = coverage.get("projected_records", [])
    finding_coverage = coverage.get("findings", {})
    audit_id = str(governance_run.get("audit") or "")
    audit_findings: list[dict[str, Any]] = []
    if audit_id:
        result = git.run(
            ["show", f"{landed_commit}:.invariant/audits/{audit_id}.yml"],
            cwd=repo,
            check=False,
        )
        if result.returncode == 0:
            audit_document = yaml.safe_load(result.stdout)
            raw_findings = (
                audit_document.get("findings", [])
                if isinstance(audit_document, dict)
                else []
            )
            audit_findings = [
                dict(finding) for finding in raw_findings if isinstance(finding, dict)
            ]
    summary = {
        "version": 1,
        "task": task,
        "status": "completed",
        "goal_digest": str(receipt.get("goal_digest") or ""),
        "landing": {
            "target": str(receipt.get("integration_target") or ""),
            "commit": landed_commit,
            "candidate_tree": str(
                receipt.get("candidate_tree")
                or receipt.get("review_candidate_tree")
                or ""
            ),
        },
        "boundary": {
            "initial": str(classification.get("boundary") or "unresolved"),
            "final": str(receipt.get("resolved_boundary") or "unresolved"),
        },
        "governance": {
            "audit": audit_id,
            "audit_findings": audit_findings,
            "selected_findings": (
                list(selected_findings) if isinstance(selected_findings, list) else []
            ),
            "finding_coverage": (
                dict(finding_coverage) if isinstance(finding_coverage, dict) else {}
            ),
            "projected_records": (
                list(projected_records) if isinstance(projected_records, list) else []
            ),
        },
        "assurance": receipt.get("assurance", {}),
    }
    local_task = task_root(repo, task)
    local_task.mkdir(parents=True, exist_ok=True)
    dump_yaml(local_task / "receipt.yml", receipt)
    dump_yaml(local_task / "summary.yml", summary)
    destination = (
        git.common_dir(repo)
        / "invariant"
        / "history"
        / "tasks"
        / task
        / landed_commit
    )
    if destination.exists():
        raise InvariantError(
            f"Invariant: completed task archive already exists for {task}@{landed_commit}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(local_task), str(destination))
    receipt_path(repo, task).unlink(missing_ok=True)
    return destination
