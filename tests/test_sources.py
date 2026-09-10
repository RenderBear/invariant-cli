from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from invariant import frontend
from invariant.errors import UsageError
from invariant.mechanics import state
from invariant.semantics import sources


def _write_catalog(repo: Path) -> None:
    invariant = repo / ".invariant"
    invariant.mkdir(parents=True, exist_ok=True)
    (invariant / "DOMAINS.yml").write_text(
        """version: 1
domains:
  - id: backend
    responsibility: Owns server-side behavior.
    authority: user:task:seed#turn-1
""",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def test_source_add_uses_managed_landing_and_absorbs_identical_untracked_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Invariant Test")
    _git(tmp_path, "config", "user.email", "invariant@example.invalid")
    _write_catalog(tmp_path)
    (tmp_path / ".invariant" / "config.yml").write_text(
        """version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
adapters:
  intent_brief: off
""",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".invariant/config.yml", ".invariant/DOMAINS.yml")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    source_path = tmp_path / ".invariant" / "sources" / "backend.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("# Backend guide\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = frontend.run(
        [
            "source",
            "add",
            "--path",
            "sources/backend.md",
            "--scope",
            "domain:backend",
        ]
    )

    assert result == 0
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert _git(tmp_path, "ls-files", ".invariant/sources/backend.md")
    registered = sources.load(tmp_path)
    assert len(registered) == 1
    assert registered[0].scope == "domain:backend"
    assert "Invariant-Boundary: no-record" in _git(
        tmp_path, "show", "-s", "--format=%B", "HEAD"
    )


def test_repository_scoped_url_needs_no_semantic_catalog_or_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Invariant Test")
    _git(tmp_path, "config", "user.email", "invariant@example.invalid")
    invariant = tmp_path / ".invariant"
    invariant.mkdir()
    (invariant / "config.yml").write_text(
        """version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
adapters:
  intent_brief: off
""",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".invariant/config.yml")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        frontend,
        "invoke",
        lambda *_args, **_kwargs: pytest.fail("--repo invoked an agent"),
    )

    result = frontend.run(
        [
            "source",
            "add",
            "--url",
            "HTTPS://Example.COM:443/standards",
            "--repo",
        ]
    )

    assert result == 0
    registered = sources.load(tmp_path)
    assert len(registered) == 1
    assert registered[0].url == "https://example.com/standards"
    assert registered[0].scope == sources.REPOSITORY_SCOPE

    result = frontend.run(
        [
            "source",
            "add",
            "--url",
            "https://Example.com:443/standards",
            "--repo",
        ]
    )

    assert result == 0
    registered = sources.load(tmp_path)
    assert len(registered) == 1
    repository_source = next(item for item in registered if item.url)
    assert repository_source.url == "https://example.com/standards"
    assert repository_source.scope == sources.REPOSITORY_SCOPE


def test_source_command_requires_one_origin_and_one_scope() -> None:
    parser = frontend.build_parser()
    with pytest.raises(UsageError):
        parser.parse_args(["source", "add", "--url", "https://example.com"])
    with pytest.raises(UsageError):
        parser.parse_args(
            [
                "source",
                "add",
                "--url",
                "https://example.com",
                "--path",
                "sources/example.md",
                "--repo",
            ]
        )
    with pytest.raises(UsageError):
        parser.parse_args(
            ["source", "add", "--url", "https://example.com", "--global"]
        )
    with pytest.raises(UsageError):
        parser.parse_args(
            ["source", "add", "--url", "https://example.com", "--project"]
        )


def test_tracked_nested_invariant_is_invalid(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    nested = tmp_path / "packages" / "api" / ".invariant" / "config.yml"
    nested.parent.mkdir(parents=True)
    nested.write_text("version: 1\n", encoding="utf-8")
    _git(tmp_path, "add", nested.relative_to(tmp_path).as_posix())

    result = state.validate(tmp_path)

    assert result[-1].endswith("Invariant state violation(s)")
    assert any("nested Invariant state" in line for line in result)
