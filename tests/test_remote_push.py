from pathlib import Path

import pytest

from invariant.application import InvariantApplication
from invariant.errors import Blocked
from invariant.mechanics import git
from invariant.mechanics.landing import PushTarget, _push_remote, _remote_push_target

from lifecycle_support import repository


def test_publication_is_denied_by_default_with_source(tmp_path: Path) -> None:
    app = repository(tmp_path / "repo")
    app.change_open(
        "publish",
        intent="publish exact result",
        supplier="user:test",
        operation_id="open-publish",
    )
    app.change_recommend("publish", operation_id="recommend-publish")
    result = app.capability_request(
        "publish",
        capability="remote.publish",
        actor="harness:test",
        resource="not-landed",
        operation_id="request-publish",
    )
    assert result.outcome.value == "denied"
    assert "policy:publication" in result.result["decision"]["explain"]["reason"]


def test_remote_target_requires_existing_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        git,
        "run",
        lambda *_args, **_kwargs: git.CompletedGit("", "", 1),
    )
    with pytest.raises(Blocked) as captured:
        _remote_push_target(Path("."), "main")
    assert captured.value.code == "remote_upstream_missing"


def test_exact_push_has_no_force_or_implicit_source(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> git.CompletedGit:
        calls.append(args)
        return git.CompletedGit("ok", "", 0)

    monkeypatch.setattr(git, "run", run)
    commit = "2" * 40
    target = PushTarget("origin", "refs/heads/stable")
    assert _push_remote(Path("."), commit, target) == [
        f"PUSHED: {commit} -> origin/stable"
    ]
    assert calls == [
        ["push", "--porcelain", "--", "origin", f"{commit}:refs/heads/stable"]
    ]
