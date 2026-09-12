"""Helpers for exercising protocol-v1 Git mechanics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from invariant.application import InvariantApplication
from invariant.mechanics import git


Planner = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


def repository(path: Path, *, commits: int = 1, planner: Planner | None = None) -> InvariantApplication:
    path.mkdir()
    git.run(["init", "-qb", "main"], cwd=path)
    git.run(["config", "user.name", "test"], cwd=path)
    git.run(["config", "user.email", "test@example.com"], cwd=path)
    git.run(["config", "commit.gpgsign", "false"], cwd=path)
    (path / "src").mkdir()
    (path / "src/a.txt").write_text("one\n", encoding="utf-8")
    git.run(["add", "-A"], cwd=path)
    git.run(["commit", "-qm", "seed"], cwd=path)
    InvariantApplication.initialize(path)
    for index in range(commits - 1):
        git.run(["commit", "-q", "--allow-empty", "-m", f"history {index}"], cwd=path)
    return InvariantApplication.bind(path, planner=planner, principal="user:test")


def open_change(
    app: InvariantApplication,
    change_id: str,
    *,
    paths: list[str] | None = None,
) -> None:
    app.change_open(
        change_id,
        intent=f"implement {change_id}",
        supplier="user:test",
        paths=paths or [f"src/{change_id}.txt"],
        operation_id=f"open-{change_id}",
    )
    app.change_recommend(change_id, operation_id=f"recommend-{change_id}")


def grant(
    app: InvariantApplication,
    change_id: str,
    capability: str,
    resource: str,
    *,
    unit: str | None = None,
    attempt: str | None = None,
    operation: str,
) -> str:
    result = app.capability_request(
        change_id,
        capability=capability,
        actor="harness:test",
        resource=resource,
        unit=unit,
        attempt=attempt,
        operation_id=operation,
    )
    token = result.result.get("token")
    assert isinstance(token, str), result.result
    return token


def begin(app: InvariantApplication, change_id: str, unit: str = "change") -> tuple[str, Path]:
    attempt = f"{unit}-attempt"
    token = grant(
        app,
        change_id,
        "worktree.create",
        f"{unit}/{attempt}",
        unit=unit,
        attempt=attempt,
        operation=f"grant-create-{change_id}-{unit}",
    )
    result = app.work_create(
        change_id,
        unit_id=unit,
        attempt_id=attempt,
        actor=f"agent:test/{unit}",
        token=token,
        operation_id=f"create-{change_id}-{unit}",
    )
    grant(
        app,
        change_id,
        "worktree.write",
        attempt,
        unit=unit,
        attempt=attempt,
        operation=f"grant-write-{change_id}-{unit}",
    )
    return attempt, Path(result.result["attempt"]["worktree"])


def implement(worktree: Path, relative: str, content: str) -> None:
    target = worktree / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git.run(["add", "-A"], cwd=worktree)
    git.run(["commit", "-qm", f"change {relative}"], cwd=worktree)


def finish(app: InvariantApplication, change_id: str, attempt: str) -> str:
    app.work_submit(
        change_id,
        attempt_id=attempt,
        actor="agent:test/worker",
        operation_id=f"submit-{change_id}-{attempt}",
    )
    token = grant(
        app,
        change_id,
        "candidate.converge",
        attempt,
        attempt=attempt,
        operation=f"grant-converge-{change_id}-{attempt}",
    )
    app.candidate_converge(
        change_id,
        attempt_id=attempt,
        token=token,
        operation_id=f"converge-{change_id}-{attempt}",
    )
    app.candidate_evidence(
        change_id, tokens={}, operation_id=f"evidence-{change_id}"
    )
    candidate = app.change_inspect(change_id).result["change"]["candidate"]
    land_token = grant(
        app,
        change_id,
        "integration.land",
        candidate["tree"],
        operation=f"grant-land-{change_id}",
    )
    result = app.integration_land(
        change_id,
        token=land_token,
        operation_id=f"land-{change_id}",
    )
    return result.result["ledger"]
