from pathlib import Path

import pytest

from invariant.application import InvariantApplication
from invariant.errors import Blocked, InvariantError
from invariant.mechanics import git


def git_repository(path: Path) -> Path:
    path.mkdir()
    git.run(["init", "-qb", "main"], cwd=path)
    git.run(["config", "user.name", "test"], cwd=path)
    git.run(["config", "user.email", "test@example.com"], cwd=path)
    git.run(["config", "commit.gpgsign", "false"], cwd=path)
    (path / "tracked.txt").write_text("accepted\n", encoding="utf-8")
    git.run(["add", "tracked.txt"], cwd=path)
    git.run(["commit", "-qm", "seed"], cwd=path)
    return path


def test_init_commits_only_the_tracked_policy_and_leaves_the_worktree_clean(
    tmp_path: Path,
) -> None:
    repo = git_repository(tmp_path / "repo")
    (repo / "notes.txt").write_text("leave me untracked\n", encoding="utf-8")

    result = InvariantApplication.initialize(repo)

    assert result.result["commit"] == git.resolve(repo, "HEAD")
    assert git.run(
        ["show", "HEAD:.invariant/config.yml"], cwd=repo
    ).stdout.startswith("version: 1\n")
    assert git.run(["show", "--format=", "--name-only", "HEAD"], cwd=repo).stdout == (
        ".invariant/config.yml"
    )
    assert git.tracked_worktree_clean(repo)
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "leave me untracked\n"


def test_init_refuses_to_capture_existing_tracked_changes(tmp_path: Path) -> None:
    repo = git_repository(tmp_path / "repo")
    (repo / "tracked.txt").write_text("unfinished\n", encoding="utf-8")

    with pytest.raises(Blocked) as captured:
        InvariantApplication.initialize(repo)

    assert captured.value.code == "dirty_initialization"
    assert not (repo / ".invariant/config.yml").exists()


def test_uncommitted_policy_is_not_accepted_state(tmp_path: Path) -> None:
    repo = git_repository(tmp_path / "repo")
    InvariantApplication.initialize(repo)
    policy = repo / ".invariant/config.yml"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace("publication: off", "publication: on"),
        encoding="utf-8",
    )

    with pytest.raises(InvariantError) as captured:
        InvariantApplication.bind(repo).state_validate()

    assert captured.value.code == "invalid_state"
    assert captured.value.data == {"paths": [".invariant/config.yml"]}


def test_unattested_policy_commit_is_rejected_by_history_validation(
    tmp_path: Path,
) -> None:
    repo = git_repository(tmp_path / "repo")
    InvariantApplication.initialize(repo)
    policy = repo / ".invariant/config.yml"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace("publication: off", "publication: on"),
        encoding="utf-8",
    )
    git.run(["add", ".invariant/config.yml"], cwd=repo)
    git.run(["commit", "-qm", "bypass policy governance"], cwd=repo)
    bypass = git.resolve(repo, "HEAD")

    with pytest.raises(InvariantError) as captured:
        InvariantApplication.bind(repo).state_validate()

    assert captured.value.code == "invalid_attestation"
    assert captured.value.data == {"commits": [bypass]}
