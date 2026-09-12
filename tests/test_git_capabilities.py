from pathlib import Path

import pytest

from invariant.errors import InvariantError
from invariant.mechanics import git


def test_required_git_capabilities_accept_feature_support(monkeypatch) -> None:
    responses = {
        ("--version",): git.CompletedGit("git version 2.test", "", 0),
        ("merge-tree", "-h"): git.CompletedGit("usage: git merge-tree [--write-tree]", "", 129),
        ("worktree", "list", "--porcelain"): git.CompletedGit("worktree /repo", "", 0),
        ("commit-tree", "-h"): git.CompletedGit("usage: git commit-tree <tree>", "", 129),
        ("update-ref", "-h"): git.CompletedGit("usage: git update-ref <ref> <new> [<old>]", "", 129),
        ("symbolic-ref", "-h"): git.CompletedGit("usage: git symbolic-ref", "", 129),
    }
    monkeypatch.setattr(git, "run", lambda args, **kwargs: responses[tuple(args)])
    git.require_capabilities(Path("/repo"))


def test_required_git_capabilities_report_every_missing_feature(monkeypatch) -> None:
    responses = {
        ("--version",): git.CompletedGit("git version 2.old", "", 0),
        ("merge-tree", "-h"): git.CompletedGit("usage: git merge-tree", "", 129),
        ("worktree", "list", "--porcelain"): git.CompletedGit("", "unsupported", 1),
        ("commit-tree", "-h"): git.CompletedGit("", "unsupported", 1),
        ("update-ref", "-h"): git.CompletedGit("", "unsupported", 1),
        ("symbolic-ref", "-h"): git.CompletedGit("", "unsupported", 1),
    }
    monkeypatch.setattr(git, "run", lambda args, **kwargs: responses[tuple(args)])
    with pytest.raises(InvariantError) as captured:
        git.require_capabilities(Path("/repo"))
    assert captured.value.code == "unsupported_git"
    assert "GIT: git version 2.old" in captured.value.lines
    assert "MISSING: git merge-tree --write-tree" in captured.value.lines
    assert "MISSING: git worktree porcelain support" in captured.value.lines
    assert "MISSING: git commit-tree" in captured.value.lines
    assert "MISSING: git update-ref compare-and-swap" in captured.value.lines
    assert "MISSING: git symbolic-ref" in captured.value.lines
