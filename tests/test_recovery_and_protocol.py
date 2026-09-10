"""Recovery from interrupted landings and abandoned work, plus protocol envelope discipline."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from lifecycle_support import AGENT, CLI, begin, codes, git, implement, invariant, repository


def test_reconcile_completes_a_landing_interrupted_before_checkout_sync(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    worktree = begin(repo, "interrupted")
    implement(worktree, "src/landed.txt", "landed\n")
    # Holding the primary index lock lets the ref update succeed while the checkout sync fails,
    # which is the crash window between compare-and-swap and read-tree.
    lock = repo / ".git" / "index.lock"
    check = repo / "checks" / "lock.sh"
    check.parent.mkdir()
    check.write_text(f"#!/bin/sh\ntouch '{lock}'\n")
    check.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add check")

    code, payload = invariant(repo, "task", "finish", "interrupted", "--check", "command:checks/lock.sh")
    assert code == 2 and codes(payload) == ["git_failed"], payload
    assert "interrupted" in git(repo, "log", "-1", "--format=%(trailers:key=Invariant-Unit,valueonly)")
    assert not (repo / "src" / "landed.txt").exists()
    assert (repo / ".invariant" / "runtime" / "briefs" / "interrupted.yml").is_file()
    lock.unlink()

    code, payload = invariant(repo, "task", "reconcile", "interrupted")
    assert code == 0, payload
    assert payload["result"]["task"]["stage"] == "completed"
    assert (repo / "src" / "landed.txt").read_text() == "landed\n"
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / ".invariant" / "runtime" / "briefs" / "interrupted.yml").exists()
    assert not list((repo / ".invariant" / "runtime" / "landing").glob("*.yml"))
    assert not worktree.exists()
    assert git(repo, "for-each-ref", "refs/heads/invariant/work/") == ""
    assert list((repo / ".invariant" / "runtime" / "history" / "tasks" / "interrupted").glob("*/summary.yml"))


def test_reconcile_leaves_an_active_task_alone(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    worktree = begin(repo, "active")
    implement(worktree, "src/active.txt", "x\n")
    code, payload = invariant(repo, "task", "reconcile", "active")
    assert code == 0, payload
    assert payload["result"]["task"]["stage"] == "implementing"
    assert worktree.is_dir()


def test_invalidate_refuses_unlanded_work_unless_discarded(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    worktree = begin(repo, "abandoned")
    implement(worktree, "src/abandoned.txt", "x\n")
    branch = git(worktree, "branch", "--show-current")

    code, payload = invariant(repo, "task", "invalidate", "abandoned")
    assert code == 1 and codes(payload) == ["work_retained"], payload
    assert worktree.is_dir()
    assert git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")

    code, payload = invariant(repo, "task", "invalidate", "abandoned", "--discard")
    assert code == 0, payload
    assert not worktree.exists()
    assert git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False) == ""
    assert not (repo / ".invariant" / "runtime" / "briefs" / "abandoned.yml").exists()

    clean = begin(repo, "untouched")
    code, payload = invariant(repo, "task", "invalidate", "untouched")
    assert code == 0, payload
    assert not clean.exists()
    assert git(repo, "for-each-ref", "refs/heads/invariant/work/") == ""


def test_runtime_clean_reaps_work_no_receipt_references(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    worktree = begin(repo, "orphan")
    branch = git(worktree, "branch", "--show-current")
    (repo / ".invariant" / "runtime" / "briefs" / "orphan.yml").unlink()

    code, payload = invariant(repo, "coordinate", "runtime", "clean")
    assert code == 0, payload
    records = {item["name"]: item["value"] for item in payload["result"]["records"]}
    assert records["ORPHANED"].startswith(f"work branch {branch} (worktree ")
    assert worktree.is_dir()

    code, payload = invariant(repo, "coordinate", "runtime", "clean", "--apply")
    assert code == 0, payload
    assert not worktree.exists()
    assert git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False) == ""


def test_global_options_are_accepted_after_the_subcommand(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    for arguments in (
        ["status", "--format", "json"],
        ["task", "status", "missing", "--format=json"],
        ["settings", "--format", "json", "--verbose"],
    ):
        completed = subprocess.run(
            [str(CLI), *arguments], cwd=repo, capture_output=True, text=True, check=False
        )
        payload = json.loads(completed.stdout)
        assert payload["protocol"] == 1, arguments
    completed = subprocess.run(
        [str(AGENT), "doctor", "--format", "json"], cwd=repo, capture_output=True, text=True, check=False
    )
    assert json.loads(completed.stdout)["command"] == "agent.doctor"


def test_unexpected_failures_keep_the_error_envelope(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    begin(repo, "unreadable")
    receipt = repo / ".invariant" / "runtime" / "briefs" / "unreadable.yml"
    receipt.chmod(0o000)
    try:
        code, payload = invariant(repo, "task", "status", "unreadable")
    finally:
        receipt.chmod(0o600)
    assert code == 2
    assert payload["status"] == "error" and payload["outcome"] == "failed"
    assert codes(payload) == ["internal_error"]


def test_harness_uses_the_core_envelope_and_preserves_exit_codes(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invariant(repo, "doctor", executable=AGENT)
    assert code == 0
    assert payload["protocol"] == 1 and payload["command"] == "agent.doctor"
    assert payload["status"] == "ok" and payload["outcome"] == "completed"

    code, payload = invariant(repo, "resolve", "missing", "--using", "codex", executable=AGENT)
    assert code == 1, payload
    assert payload["protocol"] == 1 and payload["command"] == "agent.resolve"
    assert payload["status"] == "blocked" and payload["outcome"] == "blocked"
    assert codes(payload) == ["missing_task"]

    code, payload = invariant(repo, "ask", "--using", "nothing", "x", executable=AGENT)
    assert code == 2
    assert payload["status"] == "error" and codes(payload) == ["invalid_invocation"]
