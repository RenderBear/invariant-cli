"""Shared helpers for driving the packaged CLI against throwaway repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "invariant"
AGENT = ROOT / "bin" / "invariant-agent"


def git(repo: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=check
    )
    return completed.stdout.strip()


def invariant(repo: Path, *arguments: str, executable: Path = CLI) -> tuple[int, dict]:
    completed = subprocess.run(
        [str(executable), "--format", "json", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"non-JSON output (exit {completed.returncode}): {completed.stdout!r} {completed.stderr!r}"
        )
    return completed.returncode, payload


def codes(payload: dict) -> list[str]:
    return [item.get("code") for item in payload.get("diagnostics", [])]


def repository(path: Path, *, commits: int = 1) -> Path:
    path.mkdir()
    git(path, "init", "-qb", "main")
    git(path, "config", "user.name", "test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "commit.gpgsign", "false")
    (path / "src").mkdir()
    (path / "src" / "a.txt").write_text("one\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "seed")
    for index in range(commits - 1):
        git(path, "commit", "-q", "--allow-empty", "-m", f"history {index}")
    code, _ = invariant(path, "config", "init")
    assert code == 0
    git(path, "add", "-A")
    git(path, "commit", "-qm", "invariant setup")
    return path


def begin(repo: Path, task: str) -> Path:
    code, payload = invariant(repo, "task", "begin", task, "--goal", f"goal for {task}")
    assert code == 0, payload
    return Path(payload["result"]["task"]["work"]["worktree"])


def implement(worktree: Path, relative: str, content: str) -> None:
    target = worktree / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(worktree, "add", "-A")
    git(worktree, "commit", "-qm", f"change {relative}")
