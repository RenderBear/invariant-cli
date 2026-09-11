"""Git landing guarantees under concurrency and long histories."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from lifecycle_support import CORE, CORE_COMMAND
from lifecycle_support import begin as _begin
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
    (second / "src" / "second.txt").write_text("second\n")
    check = repo / "checks" / "move.sh"
    check.parent.mkdir()
    check.write_text(
        "#!/bin/sh\n"
        f"[ -f '{marker}' ] && exit 0\n"
        f"touch '{marker}'\n"
        f"cd '{repo}' && {CORE_COMMAND} task finish second >/dev/null\n"
    )
    check.chmod(0o755)
    _git(second, "add", "-A")
    _git(second, "commit", "-qm", "second change")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add check")

    code, payload = _invariant(
        repo, "task", "finish", "first", "--check", "command:checks/move.sh"
    )
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
            [*CORE, "--format", "json", "task", "finish", task],
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
