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

    # Changing the contract record compiles an independent review. The review alone must not land.
    tree = _record_candidate(app, "second", {".invariant/records/contract/c.v1.yml": json.dumps({"version": 1, "id": "c.v1", "assertion": "c, revised", "between": ["core"], "surfaces": ["repo:schemas/c.json"], "architecture": ["architecture:docs/architecture.md#core"], "verifies": ["command:checks/ok.sh"]})})
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


def test_unbounded_reach_is_rejected(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    with pytest.raises(InvariantError) as captured:
        app.change_open("root", intent="anything", supplier="user:test", paths=["."], operation_id="open-root")
    assert captured.value.code == "unbounded_scope"
    with pytest.raises(InvariantError) as captured:
        app.change_open("empty", intent="anything", supplier="user:test", operation_id="open-empty")
    assert captured.value.code == "unbounded_scope"


def _units(n: int, prefix: str = "src/par") -> dict:
    return {
        "units": [
            {"id": f"u{i}", "objective": f"write {i}", "claims": [f"repo:{prefix}_{i}.txt"], "provides": [], "relies_on": [], "depends_on": [], "checks": []}
            for i in range(n)
        ]
    }


def test_submitted_units_release_frontier_slots(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo", planner=lambda _: _units(3), parallelism_maximum=2)
    app.change_open("slots", intent="three files", supplier="user:test", paths=[f"src/par_{i}.txt" for i in range(3)], operation_id="open-slots")
    app.change_recommend("slots", operation_id="recommend-slots")
    state = app.change_inspect("slots").result["change"]
    assert state["recommendation"]["maximum_parallelism"] == 2
    assert state["frontier"] == ["u0", "u1"]
    attempts = []
    for unit in ("u0", "u1"):
        attempt, worktree = begin(app, "slots", unit)
        implement(worktree, f"src/par_{unit[1]}.txt", f"{unit}\n")
        app.work_submit("slots", attempt_id=attempt, actor="agent:test/worker", operation_id=f"submit-{attempt}")
        attempts.append(attempt)
    assert app.change_inspect("slots").result["change"]["frontier"] == ["u2"]
    third, worktree = begin(app, "slots", "u2")
    implement(worktree, "src/par_2.txt", "u2\n")
    app.work_submit("slots", attempt_id=third, actor="agent:test/worker", operation_id=f"submit-{third}")
    for attempt in (*attempts, third):
        token = grant(app, "slots", "candidate.converge", attempt, attempt=attempt, operation=f"grant-converge-{attempt}")
        app.candidate_converge("slots", attempt_id=attempt, token=token, operation_id=f"converge-{attempt}")
    assert set(app.change_inspect("slots").result["change"]["candidate"]["units"]) == {"u0", "u1", "u2"}


def test_invalid_proposal_is_recorded_then_conservative(tmp_path: Path) -> None:
    overlapping = {"units": [
        {"id": "a", "objective": "a", "claims": ["repo:src/x"], "provides": [], "relies_on": [], "depends_on": [], "checks": []},
        {"id": "b", "objective": "b", "claims": ["repo:src/x/y.txt"], "provides": [], "relies_on": [], "depends_on": [], "checks": []},
    ]}
    app = repository(tmp_path / "repo", planner=lambda _: overlapping)
    app.change_open("bad", intent="overlap", supplier="user:test", paths=["src/x"], operation_id="open-bad")
    app.change_recommend("bad", operation_id="recommend-bad")
    state = app.change_inspect("bad").result["change"]
    assert [unit["id"] for unit in state["recommendation"]["units"]] == ["change"]
    assert state["recommendation_rejections"][0]["diagnostic"]["code"] == "overlapping_claims"


def test_serialize_directive_keeps_units_from_running_together(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    root = app.repository.root
    _governed_seed(app)
    (root / "src/a").mkdir(parents=True)
    (root / "src/b").mkdir(parents=True)
    (root / "src/a/one.txt").write_text("a\n", encoding="utf-8")
    (root / "src/b/one.txt").write_text("b\n", encoding="utf-8")
    git.run(["add", "-A"], cwd=root)
    git.run(["commit", "-qm", "two areas"], cwd=root)
    tree = _record_candidate(app, "serial", {".invariant/records/semantic/serial.yml": json.dumps({"version": 1, "id": "serial", "document": "architecture:docs/architecture.md#core", "status": "active", "applies_to": ["repo:src/a", "repo:src/b"], "directives": [{"id": "s", "kind": "serialize", "on": ["repo:src/a", "repo:src/b"]}]})})
    request = _land_request(app, "serial", tree, "first")
    action = request.result["action"]
    app.action_respond("serial", action["id"], response={"bindings": action["bindings"], "resolution": "accepted"}, actor="user:test", operation_id="accept-serial")
    app.integration_land("serial", token=_land_request(app, "serial", tree, "second").result["token"], operation_id="land-serial")

    planned = InvariantApplication.bind(root, principal="user:test", authentication=HOST_TTY, planner=lambda _: {"units": [
        {"id": "a", "objective": "a", "claims": ["repo:src/a/two.txt"], "provides": [], "relies_on": [], "depends_on": [], "checks": []},
        {"id": "b", "objective": "b", "claims": ["repo:src/b/two.txt"], "provides": [], "relies_on": [], "depends_on": [], "checks": []},
    ]})
    planned.change_open("both", intent="touch both areas", supplier="user:test", paths=["src/a/two.txt", "src/b/two.txt"], operation_id="open-both")
    planned.change_recommend("both", operation_id="recommend-both")
    state = planned.change_inspect("both").result["change"]
    assert state["recommendation"]["conflicts"] == [["a", "b"]]
    assert state["frontier"] == ["a"]
    first, worktree = begin(planned, "both", "a")
    assert planned.change_inspect("both").result["change"]["frontier"] == []
    implement(worktree, "src/a/two.txt", "a2\n")
    planned.work_submit("both", attempt_id=first, actor="agent:test/worker", operation_id=f"submit-{first}")
    assert planned.change_inspect("both").result["change"]["frontier"] == ["b"]


def test_recompute_after_target_moved_lands_on_new_parent(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    root = app.repository.root
    tokens = {}
    for change_id in ("first", "second"):
        open_change(app, change_id)
        attempt, worktree = begin(app, change_id)
        implement(worktree, f"src/{change_id}.txt", f"{change_id}\n")
        app.work_submit(change_id, attempt_id=attempt, actor="agent:test/worker", operation_id=f"submit-{change_id}")
        token = grant(app, change_id, "candidate.converge", attempt, attempt=attempt, operation=f"grant-converge-{change_id}")
        app.candidate_converge(change_id, attempt_id=attempt, token=token, operation_id=f"converge-{change_id}")
        app.candidate_evidence(change_id, tokens={}, operation_id=f"evidence-{change_id}")
        tree = app.change_inspect(change_id).result["change"]["candidate"]["tree"]
        tokens[change_id] = grant(app, change_id, "integration.land", tree, operation=f"grant-land-{change_id}")
    app.integration_land("first", token=tokens["first"], operation_id="land-first")
    moved = git.resolve(root, "main")
    with pytest.raises(Blocked) as captured:
        app.integration_land("second", token=tokens["second"], operation_id="land-second")
    assert captured.value.code == "concurrent_ref_movement"
    stale = grant(app, "second", "candidate.converge", f"recompute:{moved}", operation="grant-recompute-second")
    app.integration_recompute("second", token=stale, operation_id="recompute-second")
    state = app.change_inspect("second").result["change"]
    assert state["base"] == moved
    assert state["stage"] == "evidencing"
    assert state["evidence"] == []
    app.candidate_evidence("second", tokens={}, operation_id="evidence-second-2")
    tree = app.change_inspect("second").result["change"]["candidate"]["tree"]
    token = grant(app, "second", "integration.land", tree, operation="grant-land-second-2")
    app.integration_land("second", token=token, operation_id="land-second-2")
    head = git.resolve(root, "main")
    assert git.run(["rev-parse", f"{head}^"], cwd=root).stdout == moved
    assert git.run(["show", f"{head}:src/first.txt"], cwd=root).stdout == "first"
    assert git.run(["show", f"{head}:src/second.txt"], cwd=root).stdout == "second"
    assert app.state_validate().result["valid"] is True


def test_archive_moves_the_ledger_ref_and_history_stays_valid(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    open_change(app, "done")
    attempt, worktree = begin(app, "done")
    implement(worktree, "src/done.txt", "done\n")
    finish(app, "done", attempt)
    head_before = app.change_inspect("done").result["change"]["ledger"]
    result = app.change_archive("done", operation_id="archive-done")
    assert result.result["ref"] == "refs/invariant/archive/done"
    assert git.resolve(app.repository.root, "refs/invariant/changes/done") is None
    archived = git.resolve(app.repository.root, "refs/invariant/archive/done")
    assert archived and git.is_ancestor(app.repository.root, head_before, archived)
    validated = app.state_validate().result
    assert validated["valid"] is True and validated["archived"] == 1 and validated["changes"] == []
    assert app.change_inspect("done").result["change"]["stage"] == "completed"
