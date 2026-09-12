"""Git-grounded lifecycle guarantees under process loss and concurrency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest

from invariant.application import InvariantApplication
from invariant.errors import Blocked
from invariant.mechanics import git
from invariant.protocol import canonical_json

from lifecycle_support import begin, finish, grant, implement, open_change, repository


def test_change_ledger_survives_runtime_loss_and_application_restart(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    open_change(app, "durable")
    attempt, worktree = begin(app, "durable")
    implement(worktree, "src/durable.txt", "durable\n")
    app.work_submit(
        "durable",
        attempt_id=attempt,
        actor="agent:test/worker",
        operation_id="submit-durable",
    )
    before = app.change_handoff("durable").result["handoff"]
    runtime = app.repository.primary_worktree / ".invariant/runtime"
    git.run(["worktree", "remove", "--force", str(worktree)], cwd=app.repository.root)
    shutil.rmtree(runtime, ignore_errors=True)
    git.run(["worktree", "prune"], cwd=app.repository.root)
    assert not worktree.exists()
    restarted = InvariantApplication.bind(app.repository.root)
    after = restarted.change_inspect("durable").result["change"]
    assert after["ledger"] == before["ledger"]
    assert after["attempts"][attempt]["tip"]
    assert restarted.work.restore("durable", attempt).attempt["ref"].startswith(
        "refs/invariant/work/"
    )


def test_parallel_units_use_isolated_refs_and_converge_one_candidate(tmp_path: Path) -> None:
    def planner(_: object) -> dict:
        return {
            "units": [
                {
                    "id": "left",
                    "objective": "write left",
                    "claims": ["repo:src/left.txt"],
                    "provides": [],
                    "relies_on": [],
                    "depends_on": [],
                    "checks": [],
                },
                {
                    "id": "right",
                    "objective": "write right",
                    "claims": ["repo:src/right.txt"],
                    "provides": [],
                    "relies_on": [],
                    "depends_on": [],
                    "checks": [],
                },
            ]
        }

    app = repository(tmp_path / "repo", planner=planner)
    app.change_open(
        "parallel",
        intent="write two independent files",
        supplier="user:test",
        paths=["src/left.txt", "src/right.txt"],
        operation_id="open-parallel",
    )
    app.change_recommend("parallel", operation_id="recommend-parallel")
    left_attempt, left = begin(app, "parallel", "left")
    right_attempt, right = begin(app, "parallel", "right")
    assert left != right
    implement(left, "src/left.txt", "left\n")
    implement(right, "src/right.txt", "right\n")
    for attempt in (left_attempt, right_attempt):
        app.work_submit(
            "parallel",
            attempt_id=attempt,
            actor=f"agent:test/{attempt}",
            operation_id=f"submit-{attempt}",
        )
        token = grant(
            app,
            "parallel",
            "candidate.converge",
            attempt,
            attempt=attempt,
            operation=f"grant-converge-{attempt}",
        )
        first = app.candidate_converge(
            "parallel",
            attempt_id=attempt,
            token=token,
            operation_id=f"converge-{attempt}",
        )
        replay = app.candidate_converge(
            "parallel",
            attempt_id=attempt,
            token=token,
            operation_id=f"converge-{attempt}",
        )
        assert replay.result["ledger"] == first.result["ledger"]
    state = app.change_inspect("parallel").result["change"]
    assert set(state["candidate"]["units"]) == {"left", "right"}
    assert git.run(
        ["show", f"{state['candidate']['commit']}:src/left.txt"], cwd=app.repository.root
    ).stdout == "left"
    assert git.run(
        ["show", f"{state['candidate']['commit']}:src/right.txt"], cwd=app.repository.root
    ).stdout == "right"


def test_out_of_claim_submission_is_rejected_but_retained(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    open_change(app, "bounded", paths=["src/allowed.txt"])
    attempt, worktree = begin(app, "bounded")
    implement(worktree, "src/outside.txt", "retained\n")
    with pytest.raises(Blocked) as captured:
        app.work_submit(
            "bounded",
            attempt_id=attempt,
            actor="agent:test/worker",
            operation_id="submit-outside",
        )
    assert captured.value.code == "parallel_claim_violation"
    tip = git.resolve(app.repository.root, f"refs/invariant/work/bounded/change/{attempt}")
    assert tip
    assert git.run(["show", f"{tip}:src/outside.txt"], cwd=app.repository.root).stdout == "retained"


def test_concurrent_landings_move_target_at_most_once(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    prepared: list[tuple[str, str]] = []
    for change_id in ("first", "second"):
        open_change(app, change_id)
        attempt, worktree = begin(app, change_id)
        implement(worktree, f"src/{change_id}.txt", f"{change_id}\n")
        app.work_submit(
            change_id,
            attempt_id=attempt,
            actor="agent:test/worker",
            operation_id=f"submit-{change_id}",
        )
        token = grant(
            app,
            change_id,
            "candidate.converge",
            attempt,
            attempt=attempt,
            operation=f"grant-converge-{change_id}",
        )
        app.candidate_converge(
            change_id,
            attempt_id=attempt,
            token=token,
            operation_id=f"converge-{change_id}",
        )
        app.candidate_evidence(
            change_id, tokens={}, operation_id=f"evidence-{change_id}"
        )
        candidate = app.change_inspect(change_id).result["change"]["candidate"]
        prepared.append(
            (
                change_id,
                grant(
                    app,
                    change_id,
                    "integration.land",
                    candidate["tree"],
                    operation=f"grant-land-{change_id}",
                ),
            )
        )

    def land(item: tuple[str, str]) -> str:
        change_id, token = item
        try:
            app.integration_land(
                change_id, token=token, operation_id=f"land-{change_id}"
            )
            return "landed"
        except Blocked:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(land, prepared))
    assert outcomes.count("landed") == 1
    assert outcomes.count("blocked") == 1


def test_landing_attestation_binds_intent_plan_units_and_parent(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    open_change(app, "attested")
    attempt, worktree = begin(app, "attested")
    implement(worktree, "src/attested.txt", "attested\n")
    finish(app, "attested", attempt)
    message = git.run(["show", "-s", "--format=%B", "main"], cwd=app.repository.root).stdout
    assert "Invariant-Protocol: 1" in message
    assert "Invariant-Intent: " in message
    assert "Invariant-Plan: " in message
    assert "Invariant-Unit: change " in message
    assert "Invariant-Landing-Parent: " in message
    assert app.state_validate().result["valid"] is True


def test_post_landing_cleanup_does_not_change_attested_decisions(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    open_change(app, "cleaned")
    attempt, worktree = begin(app, "cleaned")
    implement(worktree, "src/cleaned.txt", "cleaned\n")
    finish(app, "cleaned", attempt)
    state = app.change_inspect("cleaned").result["change"]
    refs = sorted(
        [
            *(str(item["ref"]) for item in state["attempts"].values()),
            "refs/invariant/candidates/cleaned",
        ]
    )
    requested = app.capability_request(
        "cleaned",
        capability="work.discard",
        actor="user:test",
        resource=canonical_json(refs),
        operation_id="grant-cleanup-cleaned",
    )
    token = requested.result.get("token")
    assert isinstance(token, str), requested.result
    app.work_discard(
        "cleaned",
        refs=refs,
        token=token,
        operation_id="cleanup-cleaned",
    )
    assert app.state_validate().result["valid"] is True
