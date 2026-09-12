"""Git-grounded lifecycle guarantees under process loss and concurrency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest

import json

from invariant.application import InvariantApplication
from invariant.errors import Blocked, InvariantError
from invariant.governance import GovernanceStore
from invariant.harness.identity import HOST_TTY
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


def _governed_seed(app: InvariantApplication) -> None:
    root = app.repository.root
    (root / "docs").mkdir()
    (root / "docs/architecture.md").write_text("# A\n\n## Core {#core}\n\ntext\n", encoding="utf-8")
    (root / "checks").mkdir()
    (root / "checks/ok.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "checks/ok.sh").chmod(0o755)
    (root / "schemas").mkdir()
    (root / "schemas/c.json").write_text("{}\n", encoding="utf-8")
    git.run(["add", "-A"], cwd=root)
    git.run(["commit", "-qm", "governed material"], cwd=root)


def _record_candidate(app: InvariantApplication, change_id: str, files: dict[str, str]) -> str:
    open_change(app, change_id, paths=[".invariant/records"])
    attempt, worktree = begin(app, change_id)
    for relative, content in files.items():
        implement(worktree, relative, content)
    app.work_submit(change_id, attempt_id=attempt, actor="agent:test/worker", operation_id=f"submit-{change_id}")
    token = grant(app, change_id, "candidate.converge", attempt, attempt=attempt, operation=f"grant-converge-{change_id}")
    app.candidate_converge(change_id, attempt_id=attempt, token=token, operation_id=f"converge-{change_id}")
    state = app.change_inspect(change_id).result["change"]
    verifiers = {
        locator: grant(app, change_id, "verification.run", locator, operation=f"grant-verify-{change_id}-{index}")
        for index, locator in enumerate(
            sorted({*app.governance_context(paths=[".invariant/records", *state["candidate"]["paths"]]).result["obligations"]["required_verifiers"]})
        )
    }
    app.candidate_evidence(change_id, tokens=verifiers, operation_id=f"evidence-{change_id}")
    return app.change_inspect(change_id).result["change"]["candidate"]["tree"]


def _land_request(app: InvariantApplication, change_id: str, tree: str, suffix: str):
    return app.capability_request(
        change_id,
        capability="integration.land",
        actor="harness:test",
        resource=tree,
        operation_id=f"grant-land-{change_id}-{suffix}",
    )


def test_governance_landing_requires_acceptance_distinct_from_review(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    root = app.repository.root
    _governed_seed(app)
    baseline = {
        ".invariant/records/domain/core.yml": json.dumps({"version": 1, "id": "core", "responsibility": "core", "scope": ["repo:src"], "architecture": ["architecture:docs/architecture.md#core"], "contracts": ["c.v1"]}),
        ".invariant/records/contract/c.v1.yml": json.dumps({"version": 1, "id": "c.v1", "assertion": "c", "between": ["core"], "surfaces": ["repo:schemas/c.json"], "architecture": ["architecture:docs/architecture.md#core"], "verifies": ["command:checks/ok.sh"]}),
    }
    tree = _record_candidate(app, "baseline", baseline)
    first = _land_request(app, "baseline", tree, "first")
    assert first.outcome.value == "needs_input"
    assert first.result["action"]["kind"] == "accept-governance"
    resolver = InvariantApplication.bind(root, principal="agent:test/resolver")
    token = resolver.capability_request("baseline", capability="intent.resolve", actor="agent:test/resolver", resource=first.result["action"]["id"], operation_id="grant-resolve-baseline").result["token"]
    resolver.action_respond("baseline", first.result["action"]["id"], response={"bindings": first.result["action"]["bindings"], "resolution": "accepted", "summary": "ok"}, actor="agent:test/resolver", token=token, operation_id="accept-baseline")
    landed = _land_request(app, "baseline", tree, "second")
    app.integration_land("baseline", token=landed.result["token"], operation_id="land-baseline")
    assert app.state_validate().result["valid"] is True
    head = git.resolve(root, "main")
    assert head is not None
    authorities = {record.identifier: record.authority for record in GovernanceStore(root).load(head).records}
    assert authorities == {"core": "agent:test/resolver", "c.v1": "agent:test/resolver"}

    # A second record change now compiles an independent review. The review alone must not land.
    tree = _record_candidate(app, "second", {".invariant/records/semantic/s.yml": json.dumps({"version": 1, "id": "s", "document": "architecture:docs/architecture.md#core", "status": "active", "applies_to": ["repo:src"]})})
    state = app.change_inspect("second").result["change"]
    assert [item["kind"] for item in state["pending"]] == ["review-independent"]
    reviewer = InvariantApplication.bind(root, principal="agent:test/reviewer")
    review = state["pending"][0]
    token = reviewer.capability_request("second", capability="intent.resolve", actor="agent:test/reviewer", resource=review["id"], operation_id="grant-review-second").result["token"]
    reviewer.action_respond("second", review["id"], response={"bindings": review["bindings"], "verdict": "accepted", "summary": "fine", "defects": []}, actor="agent:test/reviewer", token=token, operation_id="review-second")
    reviewed = _land_request(app, "second", tree, "reviewed")
    assert reviewed.outcome.value == "needs_input"
    assert reviewed.result.get("token") is None
    assert reviewed.result["action"]["kind"] == "accept-governance"
    pending = app.change_pending("second").result["pending"]
    assert [item["kind"] for item in pending] == ["accept-governance"]
    # The reviewer, already attributed on this candidate, may still accept: it authored nothing.
    token = reviewer.capability_request("second", capability="intent.resolve", actor="agent:test/reviewer", resource=pending[0]["id"], operation_id="grant-accept-second").result["token"]
    reviewer.action_respond("second", pending[0]["id"], response={"bindings": pending[0]["bindings"], "resolution": "accepted", "summary": "ok"}, actor="agent:test/reviewer", token=token, operation_id="accept-second")
    accepted = _land_request(app, "second", tree, "accepted")
    app.integration_land("second", token=accepted.result["token"], operation_id="land-second")
    assert app.state_validate().result["valid"] is True


def test_user_accepted_record_requires_user_resolution_to_change(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    root = app.repository.root
    _governed_seed(app)
    tree = _record_candidate(app, "user-owned", {".invariant/records/domain/core.yml": json.dumps({"version": 1, "id": "core", "responsibility": "core", "scope": ["repo:src"], "architecture": ["architecture:docs/architecture.md#core"]})})
    request = _land_request(app, "user-owned", tree, "first")
    action = request.result["action"]
    app.action_respond("user-owned", action["id"], response={"bindings": action["bindings"], "resolution": "accepted"}, actor="user:test", operation_id="accept-user-owned")
    landed = _land_request(app, "user-owned", tree, "second")
    app.integration_land("user-owned", token=landed.result["token"], operation_id="land-user-owned")
    head = git.resolve(root, "main")
    assert head is not None
    assert GovernanceStore(root).load(head).records[0].authority == "user:test"

    tree = _record_candidate(app, "agent-edit", {".invariant/records/domain/core.yml": json.dumps({"version": 1, "id": "core", "responsibility": "changed by an agent", "scope": ["repo:src"], "architecture": ["architecture:docs/architecture.md#core"]})})
    request = _land_request(app, "agent-edit", tree, "first")
    assert request.outcome.value == "needs_input"
    assert request.result["action"]["resolver"] == "user"
    resolver = InvariantApplication.bind(root, principal="agent:test/resolver")
    refused = resolver.capability_request("agent-edit", capability="intent.resolve", actor="agent:test/resolver", resource=request.result["action"]["id"], operation_id="grant-resolve-agent-edit")
    assert refused.outcome.value == "needs_input"
    assert refused.result.get("token") is None


def test_user_principal_requires_authenticated_transport(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    with pytest.raises(InvariantError) as captured:
        InvariantApplication.bind(app.repository.root, principal="user:test", authentication="none")
    assert captured.value.code == "unauthenticated_principal"
    InvariantApplication.bind(app.repository.root, principal="user:test", authentication=HOST_TTY)
