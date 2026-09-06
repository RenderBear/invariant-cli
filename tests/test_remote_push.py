from pathlib import Path

import pytest

from invariant.errors import Blocked, RemotePushFailed
from invariant.mechanics import config, git, landing


def _configuration(push_remote: str, branch: str = "main") -> config.Config:
    return config.Config(
        coding_agents=("codex", "claude"),
        authority="human",
        execution="auto",
        integration_branch=branch,
        integration_branch_setting=branch,
        push_remote=push_remote,
        source="test",
        branch_source="test",
        unborn=False,
        adapters=config.AdapterOptions(),
        verification=config.VerificationOptions(),
    )


def _candidate(old: str | None = "1" * 40) -> landing.Candidate:
    return landing.Candidate(
        commit="2" * 40,
        tree="3" * 40,
        target="main",
        old=old,
        unborn=old is None,
        covers=None,
        reach_base=old,
    )


@pytest.mark.parametrize(
    ("accepted", "proposed", "enabled"),
    [("off", "off", False), ("off", "on", False), ("on", "off", False), ("on", "on", True)],
)
def test_remote_push_requires_accepted_and_proposed_opt_in(
    monkeypatch: pytest.MonkeyPatch, accepted: str, proposed: str, enabled: bool
) -> None:
    candidate = _candidate()

    def resolve_at(_: Path, ref: str, __: str) -> config.Config:
        return _configuration(accepted if ref == candidate.old else proposed)

    monkeypatch.setattr(landing.config, "resolve_at", resolve_at)
    assert landing._remote_push_enabled(Path("."), candidate) is enabled


def test_unborn_integration_never_pushes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        landing.config,
        "resolve_at",
        lambda *_: pytest.fail("unborn policy must not read candidate configuration"),
    )
    assert landing._remote_push_enabled(Path("."), _candidate(old=None)) is False


def test_landing_rejects_a_tree_changed_after_adapter_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(landing.git, "require_capabilities", lambda _repo: None)
    monkeypatch.setattr(
        landing.git,
        "run",
        lambda *_args, **_kwargs: git.CompletedGit("", "", 0),
    )
    monkeypatch.setattr(landing, "_construct", lambda *_args: _candidate())
    request = landing.LandRequest(
        mode="merge",
        subject="reviewed task",
        units=("task",),
        scopes=("area.root",),
        boundary="no-record",
        merge_branch="invariant/work/task",
        target="main",
        expected_tree="4" * 40,
    )
    with pytest.raises(Blocked, match="changed after its adapter review") as captured:
        landing.verify_and_land(Path("."), request)
    assert captured.value.code == "stale_adapter_review"


def test_remote_target_requires_existing_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> git.CompletedGit:
        calls.append(args)
        values = {
            ("config", "--get", "branch.main.remote"): git.CompletedGit("origin", "", 0),
            ("config", "--get", "branch.main.merge"): git.CompletedGit("refs/heads/stable", "", 0),
            ("remote",): git.CompletedGit("origin", "", 0),
            ("check-ref-format", "refs/heads/stable"): git.CompletedGit("", "", 0),
        }
        return values[tuple(args)]

    monkeypatch.setattr(landing.git, "run", run)
    target = landing._remote_push_target(Path("."), "main")
    assert target == landing.PushTarget("origin", "refs/heads/stable")
    assert ["remote"] in calls


def test_remote_target_rejects_missing_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        landing.git,
        "run",
        lambda *_args, **_kwargs: git.CompletedGit("", "", 1),
    )
    with pytest.raises(Blocked, match="no usable upstream") as captured:
        landing._remote_push_target(Path("."), "main")
    assert captured.value.code == "remote_upstream_missing"


def test_remote_push_uses_exact_candidate_without_executing_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **_: object) -> git.CompletedGit:
        calls.append(args)
        return git.CompletedGit("ok", "", 0)

    monkeypatch.setattr(landing.git, "run", run)
    candidate = _candidate()
    target = landing.PushTarget("origin", "refs/heads/stable")
    assert landing._push_remote(Path("."), candidate, target) == [
        f"PUSHED: {candidate.commit} -> origin/stable"
    ]
    assert calls == [
        [
            "push",
            "--porcelain",
            "--",
            "origin",
            f"{candidate.commit}:refs/heads/stable",
        ]
    ]


def test_remote_failure_reports_retained_local_landing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        landing.git,
        "run",
        lambda *_args, **_kwargs: git.CompletedGit("", "rejected", 1),
    )
    with pytest.raises(RemotePushFailed, match="local integration commit is retained") as captured:
        landing._push_remote(
            Path("."), _candidate(), landing.PushTarget("origin", "refs/heads/main")
        )
    assert captured.value.code == "remote_push_failed"
    assert "REMOTE: rejected" in captured.value.lines
