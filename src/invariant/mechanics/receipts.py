from __future__ import annotations

import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

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
    governance_state = {
        "governance_digest": governance.digest(repo, selected),
        "integration_governance_digest": (
            governance.digest(repo, selected, head) if head != "unborn" else git.hash_text(repo, "")
        ),
        "boundary": boundary,
    }
    if posture:
        governance_state["posture"] = posture
    receipt = {
        "version": 1,
        "repository": repository_identity(repo, target),
        "task": task,
        "goal_digest": git.hash_text(repo, goal),
        "integration_target": target,
        "integration_head": head,
        "mechanics_digest": mechanics_digest(),
        "scope": {
            "paths": sorted(set(paths)),
            "interfaces": sorted(set(interfaces)),
            "domains": selected,
        },
        "governance": governance_state,
        "adapters": sorted(set(adapters)),
    }
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
    governance_state = receipt.get("governance") if isinstance(receipt.get("governance"), dict) else {}
    if governance.digest(repo, selected) != governance_state.get("governance_digest"):
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
    integration_digest = governance_state.get("integration_governance_digest")
    if head_advanced:
        if "unborn" in {cached_head, current_head}:
            raise Blocked("STALE: integration branch birth state changed", code="stale_receipt")
        if not git.is_ancestor(repo, cached_head, current_head):
            raise Blocked(
                "STALE: integration history no longer descends from the cached head", code="stale_receipt"
            )
        integration_digest = governance.digest(repo, selected, current_head)
        if integration_digest != governance_state.get("integration_governance_digest"):
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
        governance_state["integration_governance_digest"] = integration_digest
        receipt["governance"] = governance_state
        save(repo, task, receipt)
    output: list[str] = []
    if head_advanced:
        output.append(f"HEAD: advanced {cached_head}..{current_head} — mergeable, brief reused")
    if goal_changed:
        output.append("GOAL: changed text accepted for cached semantic envelope")
    output.extend([f"BRIEF: fresh {task}", "REUSE: cached semantic envelope"])
    if governance_state.get("posture"):
        output.append(f"POSTURE: {governance_state['posture']}")
    output.append(f"BOUNDARY: {governance_state.get('boundary', '')}")
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
