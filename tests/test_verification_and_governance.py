"""Verifier time limits and the audit vocabulary for semantic records."""

from __future__ import annotations

import time
from pathlib import Path

from lifecycle_support import begin, codes, git, implement, invariant, repository


def test_command_verifiers_inherit_the_repository_time_limit(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    config = repo / ".invariant" / "config.yml"
    config.write_text(config.read_text() + "verification:\n  timeout: 1\n")
    check = repo / "checks" / "hang.sh"
    check.parent.mkdir()
    check.write_text("#!/bin/sh\nsleep 30\n")
    check.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add hanging check")
    worktree = begin(repo, "hang")
    implement(worktree, "src/hang.txt", "x\n")

    started = time.perf_counter()
    code, payload = invariant(repo, "task", "finish", "hang", "--check", "command:checks/hang.sh")
    elapsed = time.perf_counter() - started
    assert code == 1 and codes(payload) == ["verification_failed"], payload
    assert "timed out" in payload["diagnostics"][0]["message"]
    records = payload["result"]["records"]
    check = next(item["value"] for item in records if item["name"] == "CHECK")
    assert check.startswith("timed out after 1s — command:checks/hang.sh")
    assert elapsed < 20, f"the hung verifier held the landing for {elapsed:.0f}s"
    assert git(repo, "cat-file", "-e", "main:src/hang.txt", check=False) == ""


def test_audits_can_propose_semantic_records(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invariant(repo, "governance", "begin", "meaning")
    assert code == 0, payload
    records = {item["name"]: item["value"] for item in payload["result"]["records"]}
    worktree = Path(records["WORKTREE"])
    (worktree / "docs").mkdir()
    (worktree / "docs" / "architecture.md").write_text(
        "# Architecture\n\n## Source ownership\n\nThe source module owns its value.\n"
    )
    findings = tmp_path / "findings.yml"
    findings.write_text(
        "version: 1\n"
        "findings:\n"
        "  - id: ownership\n"
        "    summary: The source module has one stable owner.\n"
        "    evidence: [repo:src/a.txt]\n"
        "    proposed: semantic\n"
        "    disposition: adoptable\n"
        "    authority: user:task:meaning#decision\n"
        "    records:\n"
        "      - kind: semantic\n"
        "        value:\n"
        "          id: source-ownership\n"
        "          document: architecture:docs/architecture.md#source-ownership\n"
        "          authority: user:task:meaning#decision\n"
        "          status: active\n"
        "          applies_to: [repo:src/a.txt]\n"
    )
    code, payload = invariant(repo, "governance", "audit-save", "meaning", "--input", str(findings))
    assert code == 0, payload
    code, payload = invariant(repo, "governance", "adopt", "meaning", "--all-ready")
    assert code == 0, payload
    code, payload = invariant(repo, "governance", "project", "meaning")
    assert code == 0, payload
    assert payload["result"]["coverage"]["findings"]["ownership"]["records"] == ["semantic:source-ownership"]
