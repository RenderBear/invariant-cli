"""Observable lifecycle guarantees under concurrency, hostile input, and long histories."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from lifecycle_support import CLI
from lifecycle_support import begin as _begin
from lifecycle_support import codes as _codes
from lifecycle_support import git as _git
from lifecycle_support import implement as _implement
from lifecycle_support import invariant as _invariant
from lifecycle_support import repository as _repository


def _lifecycle_seconds(repo: Path, task: str) -> float:
    started = time.perf_counter()
    worktree = _begin(repo, task)
    _implement(worktree, f"src/{task}.txt", f"{task}\n")
    code, payload = _invariant(repo, "task", "finish", task)
    assert code == 0, payload
    return time.perf_counter() - started


def test_finish_cost_does_not_scale_with_repository_history(tmp_path: Path) -> None:
    short = _repository(tmp_path / "short", commits=20)
    long = _repository(tmp_path / "long", commits=600)
    short_seconds = min(_lifecycle_seconds(short, f"warm{i}") for i in range(2))
    long_seconds = min(_lifecycle_seconds(long, f"warm{i}") for i in range(2))
    assert long_seconds < short_seconds * 3, (
        f"a 600-commit history cost {long_seconds:.1f}s per task versus {short_seconds:.1f}s"
    )


def test_finish_cost_does_not_scale_with_unattested_history(tmp_path: Path) -> None:
    short = _repository(tmp_path / "short")
    long = _repository(tmp_path / "long")
    _lifecycle_seconds(short, "baseline")
    _lifecycle_seconds(long, "baseline")
    for index in range(400):
        _git(long, "commit", "-q", "--allow-empty", "-m", f"ordinary history {index}")
    short_seconds = _lifecycle_seconds(short, "after-gap")
    long_seconds = _lifecycle_seconds(long, "after-gap")
    assert long_seconds < short_seconds * 3, (
        f"a 400-commit unattested suffix cost {long_seconds:.1f}s per task versus "
        f"{short_seconds:.1f}s without the suffix"
    )


def test_racing_landings_rebuild_and_recover_without_manual_retry(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    first = _begin(repo, "first")
    second = _begin(repo, "second")
    _implement(first, "src/first.txt", "first\n")
    marker = tmp_path / "landed-second"
    # The check moves the integration branch by landing the other task mid-verification.
    (second / "src" / "second.txt").write_text("second\n")
    check = repo / "checks" / "move.sh"
    check.parent.mkdir()
    check.write_text(
        "#!/bin/sh\n"
        f"[ -f '{marker}' ] && exit 0\n"
        f"touch '{marker}'\n"
        f"cd '{repo}' && '{CLI}' task finish second >/dev/null\n"
    )
    check.chmod(0o755)
    _git(second, "add", "-A")
    _git(second, "commit", "-qm", "second change")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add check")

    code, payload = _invariant(repo, "task", "finish", "first", "--check", "command:checks/move.sh")
    assert code == 0, payload
    assert payload["result"]["task"]["stage"] == "completed"
    assert marker.exists()
    assert _git(repo, "show", "main:src/second.txt") == "second"
    assert _git(repo, "show", "main:src/first.txt") == "first"


def test_parallel_disjoint_finishes_converge_without_lost_work(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    tasks = [f"parallel-{index}" for index in range(6)]
    for task in tasks:
        worktree = _begin(repo, task)
        _implement(worktree, f"src/{task}.txt", f"{task}\n")

    processes = [
        subprocess.Popen(
            [str(CLI), "--format", "json", "task", "finish", task],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for task in tasks
    ]
    results = [process.communicate() for process in processes]
    payloads = [json.loads(stdout) for stdout, _ in results]
    assert all(process.returncode == 0 for process in processes), json.dumps(
        payloads, indent=2
    )
    assert all(payload["result"]["task"]["stage"] == "completed" for payload in payloads)
    assert all(_git(repo, "show", f"main:src/{task}.txt") == task for task in tasks)
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 0, payload


def test_assessment_cannot_land_governed_prose_without_a_review(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    (repo / "docs").mkdir()
    (repo / "docs" / "architecture.md").write_text(
        "# Architecture\n\n## Source ownership\n\nThe source module owns its value.\n"
    )
    (repo / ".invariant" / "DOMAINS.yml").write_text(
        "version: 1\n"
        "domains:\n"
        "  - id: source\n"
        "    responsibility: Owns the source value.\n"
        "    authority: user:task:seed#decision\n"
        "    architecture: [architecture:docs/architecture.md#source-ownership]\n"
    )
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-qm",
        "record ownership",
        "-m",
        "Invariant-Unit: seed\nInvariant-Scope: area.root\nInvariant-Boundary: no-record",
    )
    worktree = _begin(repo, "rewrite")
    _implement(
        worktree,
        "docs/architecture.md",
        "# Architecture\n\n## Source ownership\n\nAnything may own the value.\n",
    )
    code, payload = _invariant(repo, "task", "status", "rewrite")
    goal_digest = payload["result"]["task"]["goal_digest"]
    assessment = tmp_path / "assessment.yml"
    assessment.write_text(
        "version: 1\n"
        f"goal_digest: {goal_digest}\n"
        "paths: [docs/architecture.md]\n"
        "interfaces: []\n"
        "domains: []\n"
        "boundary: {disposition: recorded}\n"
        "governance: [architecture:docs/architecture.md#source-ownership]\n"
        "architecture_reviews: [architecture:docs/architecture.md#source-ownership]\n"
        "checks: []\n"
        "allow_open: true\n"
    )
    before = _git(repo, "rev-parse", "main")
    code, payload = _invariant(repo, "task", "finish", "rewrite", "--assessment", str(assessment))
    assert code == 1
    assert _codes(payload) == ["semantic_review_required"], payload
    assert _git(repo, "rev-parse", "main") == before

    code, payload = _invariant(repo, "task", "finish", "rewrite")
    assert code == 0 and payload["outcome"] == "needs_input", payload
    action = payload["result"]["task"]["actions"][0]["id"]
    code, payload = _invariant(repo, "task", "action", "rewrite", action)
    context = payload["result"]["action"]["context"]
    review = tmp_path / "review.yml"
    review.write_text(
        "version: 1\n"
        f"review_id: {context['review_id']}\n"
        f"candidate_tree: {context['candidate_tree']}\n"
        "verdict: accepted\n"
        "summary: The ownership decision is deliberately relaxed.\n"
        "semantic_effect: recorded\n"
        "authority: user:task:rewrite#review\n"
        "candidate_defects: []\n"
    )
    code, payload = _invariant(repo, "task", "respond", "rewrite", action, "--input", str(review))
    assert code == 0, payload
    assert payload["result"]["task"]["stage"] == "completed"
    assert "Anything may own" in _git(repo, "show", "main:docs/architecture.md")


def test_concurrent_lease_acquisition_grants_one_holder(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    processes = [
        subprocess.Popen(
            [
                str(CLI), "--format", "json", "coordinate", "lease", "acquire", "shared",
                "--path", "src/a.txt", "--owner", f"racer{index}", "--duration", "300",
            ],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(8)
    ]
    results = [process.communicate() for process in processes]
    winners = [
        json.loads(stdout)["result"]
        for process, (stdout, _) in zip(processes, results)
        if process.returncode == 0
    ]
    assert len(winners) == 1, [stdout for stdout, _ in results]
    losers = [json.loads(stdout) for process, (stdout, _) in zip(processes, results) if process.returncode]
    assert all("live lease for 'shared' exists" in loser["diagnostics"][0]["message"] for loser in losers)
    lease = repo / ".invariant" / "runtime" / "leases" / "shared.yml"
    assert lease.is_file()


def test_lease_units_and_landing_subjects_reject_hostile_values(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    code, payload = _invariant(
        repo, "coordinate", "lease", "acquire", "../../escaped", "--path", "src/a.txt"
    )
    assert code == 2
    assert "invalid lease unit" in payload["diagnostics"][0]["message"]
    assert not (repo / ".invariant" / "escaped.yml").exists()
    assert not (repo / ".invariant" / "runtime" / "escaped.yml").exists()

    worktree = _begin(repo, "subject")
    _implement(worktree, "src/subject.txt", "x\n")
    forged = "Legit subject\n\nInvariant-Unit: other-unit\nInvariant-Boundary: recorded"
    code, payload = _invariant(repo, "task", "finish", "subject", "--subject", forged)
    assert code == 2, payload
    assert "subject must be one non-empty line" in payload["diagnostics"][0]["message"]
    assert _git(repo, "log", "-1", "--format=%s") == "invariant setup"


def test_repository_local_packages_cannot_hijack_the_cli(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    for package in ("invariant", "yaml"):
        (repo / package).mkdir()
        (repo / package / "__init__.py").write_text("raise SystemExit('hijacked by repository code')\n")
    code, payload = _invariant(repo, "status")
    assert code == 0, payload
    assert payload["command"] == "status"
