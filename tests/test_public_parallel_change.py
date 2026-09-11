"""Public change planning, parallel dispatch, and causal contract synchronization."""

from __future__ import annotations

import json
import os
import pty
import subprocess
from pathlib import Path

import yaml

from lifecycle_support import CLI, git, repository


def _fake_codex(path: Path) -> Path:
    executable = path / "codex"
    executable.write_text(
        r'''#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli parallel-test'
  exit 0
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  echo 'Logged in using test account'
  exit 0
fi
output=
schema=false
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output=$1
  elif [ "$1" = "--output-schema" ]; then
    schema=true
  fi
  shift
done
[ -n "$output" ] || exit 3
request=$(cat)
if [ "$schema" = true ]; then
  case "$request" in
    *"Request kind: task.respond"*)
      printf '%s\n' review >>"$FAKE_AGENT_LOG"
      review_id=$(printf '%s\n' "$request" | sed -n 's/.*"review_id": "\([^"]*\)".*/\1/p' | head -n 1)
      candidate_tree=$(printf '%s\n' "$request" | sed -n 's/.*"candidate_tree": "\([^"]*\)".*/\1/p' | head -n 1)
      if grep -q 'The corrected source rule is explicit.' docs/architecture.md; then
        cat >"$output" <<JSON
{"version":1,"review_id":"$review_id","candidate_tree":"$candidate_tree","verdict":"accepted","summary":"The corrected candidate records the requested source rule.","semantic_effect":"recorded","authority":"agent:fake","review_mode":"independent","candidate_defects":[],"retained_discoveries":[]}
JSON
      else
        cat >"$output" <<JSON
{"version":1,"review_id":"$review_id","candidate_tree":"$candidate_tree","verdict":"rejected","summary":"The candidate records the wrong source rule.","semantic_effect":"recorded","authority":"agent:fake","review_mode":"independent","candidate_defects":["docs/architecture.md must state the corrected source rule."],"retained_discoveries":[]}
JSON
      fi
      ;;
    *)
      printf '%s\n' plan >>"$FAKE_AGENT_LOG"
      case "$request" in
    *"Repair an invalid execution plan"*)
      attempts=$(grep -c '^plan$' "$FAKE_AGENT_LOG")
      if [ "$attempts" -eq 1 ]; then
        cat >"$output" <<'JSON'
{"strategy":"parallel","summary":"Invalid code-symbol dependency.","units":[{"id":"one","objective":"First invalid unit.","dependencies":[],"paths":["src"],"interfaces":[],"governance":["src.api"],"provides":["src.api"],"relies_on":[],"verifies":["test:tests/test_a.py"]},{"id":"two","objective":"Second invalid unit.","dependencies":["one"],"paths":["docs"],"interfaces":[],"governance":[],"provides":[],"relies_on":["src.api"],"verifies":["test:tests/test_b.py"]}]}
JSON
      else
        printf '%s\n' '{"strategy":"single","summary":"Use one cohesive unit after the invalid dependency vocabulary was rejected.","units":[]}' >"$output"
      fi
      ;;
    *"Discard generated worker caches"*)
      cat >"$output" <<'JSON'
{"strategy":"parallel","summary":"Two independent cache-producing work items.","units":[{"id":"alpha","objective":"Create the alpha output and verifier.","dependencies":[],"paths":["alpha","checks/alpha.sh"],"interfaces":[],"governance":[],"provides":[],"relies_on":[],"verifies":["command:checks/alpha.sh"]},{"id":"beta","objective":"Create the beta output and verifier.","dependencies":[],"paths":["beta","checks/beta.sh"],"interfaces":[],"governance":[],"provides":[],"relies_on":[],"verifies":["command:checks/beta.sh"]}]}
JSON
      ;;
    *"Build a frontend and backend"*)
      cat >"$output" <<'JSON'
{"strategy":"parallel","summary":"Establish the API contract, then build independent consumers.","units":[{"id":"contract","objective":"Establish the shared parcel API contract and its check.","dependencies":[],"paths":["contract","checks/contract.sh"],"interfaces":[],"governance":["contract:parcel.api"],"provides":["contract:parcel.api"],"relies_on":[],"verifies":["test:checks/contract.sh"]},{"id":"frontend","objective":"Build the frontend against the converged parcel API contract.","dependencies":["contract"],"paths":["frontend","checks/frontend.sh"],"interfaces":[],"governance":[],"provides":[],"relies_on":["contract:parcel.api"],"verifies":["test:checks/frontend.sh"]},{"id":"backend","objective":"Build the backend against the converged parcel API contract.","dependencies":["contract"],"paths":["backend","checks/backend.sh"],"interfaces":[],"governance":[],"provides":[],"relies_on":["contract:parcel.api"],"verifies":["test:checks/backend.sh"]}]}
JSON
      ;;
    *)
      printf '%s\n' '{"strategy":"single","summary":"One cohesive edit.","units":[]}' >"$output"
      ;;
      esac
      ;;
  esac
else
  case "$request" in
    *"candidate author correcting"*)
      printf '%s\n' write:correction >>"$FAKE_AGENT_LOG"
      printf '%s\n' '# Architecture' '' '## Source rule {#source-rule}' '' 'The corrected source rule is explicit.' >docs/architecture.md
      printf '%s\n' 'Corrected the rejected source rule.' >"$output"
      ;;
    *"Correct a rejected governed candidate"*)
      printf '%s\n' write:initial >>"$FAKE_AGENT_LOG"
      printf '%s\n' '# Architecture' '' '## Source rule {#source-rule}' '' 'The wrong source rule remains.' >docs/architecture.md
      printf '%s\n' 'Changed the source rule.' >"$output"
      ;;
    *"Work item: alpha"*)
      printf '%s\n' write:alpha >>"$FAKE_AGENT_LOG"
      mkdir -p alpha checks src/__pycache__
      printf '%s\n' alpha >alpha/result.txt
      printf '%s\n' '#!/bin/sh' 'test -f alpha/result.txt' >checks/alpha.sh
      chmod +x checks/alpha.sh
      printf '%s\n' cache >src/__pycache__/alpha.pyc
      printf '%s\n' 'Built alpha.' >"$output"
      ;;
    *"Work item: beta"*)
      printf '%s\n' write:beta >>"$FAKE_AGENT_LOG"
      mkdir -p beta checks src/__pycache__
      printf '%s\n' beta >beta/result.txt
      printf '%s\n' '#!/bin/sh' 'test -f beta/result.txt' >checks/beta.sh
      chmod +x checks/beta.sh
      printf '%s\n' cache >src/__pycache__/beta.pyc
      printf '%s\n' 'Built beta.' >"$output"
      ;;
    *"Work item: contract"*)
      printf '%s\n' write:contract >>"$FAKE_AGENT_LOG"
      mkdir -p contract checks
      printf '%s\n' 'parcel-api-v1' >contract/api.txt
      printf '%s\n' '#!/bin/sh' 'set -eu' 'test -f contract/api.txt' >checks/contract.sh
      chmod +x checks/contract.sh
      printf '%s\n' 'Established the parcel API contract.' >"$output"
      ;;
    *"Work item: frontend"*)
      printf '%s\n' write:frontend >>"$FAKE_AGENT_LOG"
      test -f contract/api.txt
      mkdir -p "$FAKE_BARRIER" frontend checks
      : >"$FAKE_BARRIER/frontend"
      attempts=0
      while [ ! -f "$FAKE_BARRIER/backend" ]; do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 100 ] || exit 21
        sleep 0.02
      done
      printf '%s\n' 'frontend uses parcel-api-v1' >frontend/app.txt
      printf '%s\n' '#!/bin/sh' 'set -eu' 'grep -q parcel-api-v1 frontend/app.txt' >checks/frontend.sh
      chmod +x checks/frontend.sh
      printf '%s\n' 'Built the frontend.' >"$output"
      ;;
    *"Work item: backend"*)
      printf '%s\n' write:backend >>"$FAKE_AGENT_LOG"
      test -f contract/api.txt
      mkdir -p "$FAKE_BARRIER" backend checks
      : >"$FAKE_BARRIER/backend"
      attempts=0
      while [ ! -f "$FAKE_BARRIER/frontend" ]; do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 100 ] || exit 22
        sleep 0.02
      done
      printf '%s\n' 'backend uses parcel-api-v1' >backend/app.txt
      printf '%s\n' '#!/bin/sh' 'set -eu' 'grep -q parcel-api-v1 backend/app.txt' >checks/backend.sh
      chmod +x checks/backend.sh
      printf '%s\n' 'Built the backend.' >"$output"
      ;;
    *)
      printf '%s\n' write:single >>"$FAKE_AGENT_LOG"
      printf '%s\n' 'small change' >>src/a.txt
      printf '%s\n' 'Made one small change.' >"$output"
      ;;
  esac
fi
printf '%s\n' '{"type":"thread.started","thread_id":"parallel-test-session"}'
printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}'
''',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _change(
    repo: Path,
    executable: Path,
    log: Path,
    barrier: Path,
    goal: str,
    change_id: str,
    *,
    boundary: str = "no-record",
):
    environment = {
        **os.environ,
        "INVARIANT_CODEX": str(executable),
        "INVARIANT_HOME": str(repo.parent / "invariant-home"),
        "FAKE_AGENT_LOG": str(log),
        "FAKE_BARRIER": str(barrier),
    }
    completed = subprocess.run(
        [
            str(CLI),
            "--format",
            "json",
            "change",
            "--id",
            change_id,
            "--boundary",
            boundary,
            goal,
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def test_public_change_parallelizes_ready_consumers_after_contract_convergence(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    completed, payload = _change(
        repo,
        fake,
        log,
        tmp_path / "barrier",
        "Build a frontend and backend for parcel tracking against one shared API contract.",
        "parcel-stack",
    )

    assert completed.returncode == 0, (completed.stderr, payload)
    plan = payload["result"]["plan"]
    assert plan["strategy"] == "parallel"
    assert [item["id"] for item in plan["units"]] == [
        "parcel-stack.contract",
        "parcel-stack.frontend",
        "parcel-stack.backend",
    ]
    assert (repo / "contract" / "api.txt").read_text().strip() == "parcel-api-v1"
    assert "parcel-api-v1" in (repo / "frontend" / "app.txt").read_text()
    assert "parcel-api-v1" in (repo / "backend" / "app.txt").read_text()
    calls = log.read_text().splitlines()
    assert calls[:2] == ["plan", "write:contract"]
    assert set(calls[2:]) == {"write:frontend", "write:backend"}

    landing = git(repo, "rev-parse", "HEAD")
    assert git(repo, "log", "-1", "--format=%(trailers:key=Invariant-Plan,valueonly)") == "parcel-stack"
    summary_path = (
        repo
        / ".invariant"
        / "runtime"
        / "history"
        / "tasks"
        / "parcel-stack"
        / landing
        / "summary.yml"
    )
    summary = yaml.safe_load(summary_path.read_text())
    assert summary["coordination"] == {
        "strategy": "parallel",
        "summary": "Establish the API contract, then build independent consumers.",
        "plan": "parcel-stack",
        "units": [
            "parcel-stack.contract",
            "parcel-stack.frontend",
            "parcel-stack.backend",
        ],
    }
    assert not (repo / ".invariant" / "runtime" / "plans" / "parcel-stack.yml").exists()
    assert not list((repo / ".invariant" / "runtime" / "leases").glob("*.yml"))
    assert len(git(repo, "worktree", "list", "--porcelain").split("\n\n")) == 1


def test_public_change_keeps_a_small_edit_single(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    completed, payload = _change(
        repo,
        fake,
        log,
        tmp_path / "barrier",
        "Append one small marker.",
        "small-marker",
    )

    assert completed.returncode == 0, (completed.stderr, payload)
    assert payload["result"]["plan"]["strategy"] == "single"
    assert log.read_text().splitlines() == ["plan", "write:single"]
    assert (repo / "src" / "a.txt").read_text().endswith("small change\n")
    assert not (repo / ".invariant" / "runtime" / "plans").exists()


def test_public_change_repairs_invalid_plan_before_dispatch(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    completed, payload = _change(
        repo,
        fake,
        log,
        tmp_path / "barrier",
        "Repair an invalid execution plan before changing the repository.",
        "plan-repair",
    )

    assert completed.returncode == 0, (completed.stderr, payload)
    assert payload["result"]["plan"]["strategy"] == "single"
    assert payload["result"]["plan"]["attempts"] == 2
    assert log.read_text().splitlines() == ["plan", "plan", "write:single"]
    assert not list((repo / ".invariant" / "runtime" / "leases").glob("*.yml"))


def test_parallel_workers_discard_only_generated_untracked_caches(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    completed, payload = _change(
        repo,
        fake,
        log,
        tmp_path / "barrier",
        "Discard generated worker caches while keeping both requested outputs.",
        "cache-hygiene",
    )

    assert completed.returncode == 0, (completed.stderr, payload)
    assert payload["result"]["plan"]["strategy"] == "parallel"
    assert (repo / "alpha" / "result.txt").read_text().strip() == "alpha"
    assert (repo / "beta" / "result.txt").read_text().strip() == "beta"
    assert not (repo / "src" / "__pycache__").exists()
    assert "__pycache__" not in git(repo, "show", "--stat", "--oneline", "HEAD")


def test_public_change_routes_reviewer_defects_to_author_then_rereviews(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    architecture = repo / "docs" / "architecture.md"
    architecture.parent.mkdir()
    architecture.write_text(
        "# Architecture\n\n## Source rule {#source-rule}\n\nThe original source rule.\n",
        encoding="utf-8",
    )
    domain = repo / ".invariant" / "records" / "domain" / "source.yml"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "version: 1\nid: source\nresponsibility: Owns the source rule.\n"
        "authority: user:task:baseline#decision\n"
        "architecture: [architecture:docs/architecture.md#source-rule]\n"
        "contracts: []\n",
        encoding="utf-8",
    )
    git(repo, "add", "docs/architecture.md", ".invariant/records/domain/source.yml")
    git(repo, "commit", "-qm", "record source rule")

    completed, payload = _change(
        repo,
        fake,
        log,
        tmp_path / "barrier",
        "Correct a rejected governed candidate by recording the corrected source rule.",
        "review-correction",
        boundary="unresolved",
    )

    assert completed.returncode == 0, (completed.stderr, payload)
    assert payload["result"]["review_repairs"][0]["rejected_tree"]
    assert "corrected source rule" in architecture.read_text()
    assert log.read_text().splitlines() == [
        "plan",
        "write:initial",
        "review",
        "write:correction",
        "review",
    ]
    landing = git(repo, "rev-parse", "HEAD")
    rejected = list(
        (
            repo
            / ".invariant"
            / "runtime"
            / "history"
            / "tasks"
            / "review-correction"
            / landing
            / "rejected-reviews"
        ).glob("*.yml")
    )
    assert len(rejected) == 1
    saved = yaml.safe_load(rejected[0].read_text())
    assert saved["candidate_defects"] == [
        "docs/architecture.md must state the corrected source rule."
    ]


def test_human_change_resumes_review_without_reimplementing(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fake = _fake_codex(tmp_path)
    log = tmp_path / "agent.log"
    barrier = tmp_path / "barrier"
    config = repo / ".invariant" / "config.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("authority: agent", "authority: human"),
        encoding="utf-8",
    )
    architecture = repo / "docs" / "architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "# Architecture\n\n## Source boundary {#source-boundary}\n\nThe source value stays repository-owned.\n",
        encoding="utf-8",
    )
    domain = repo / ".invariant" / "records" / "domain" / "source.yml"
    domain.parent.mkdir(parents=True)
    domain.write_text(
        "version: 1\nid: source\nresponsibility: Owns source behavior.\n"
        "authority: user:task:test#decision\n"
        "architecture: [architecture:docs/architecture.md#source-boundary]\n",
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "configure human source authority")
    environment = {
        **os.environ,
        "INVARIANT_CODEX": str(fake),
        "INVARIANT_HOME": str(tmp_path / "invariant-home"),
        "FAKE_AGENT_LOG": str(log),
        "FAKE_BARRIER": str(barrier),
    }
    command = [
        str(CLI),
        "change",
        "--id",
        "human-source",
        "--boundary",
        "no-record",
        "--domain",
        "source",
        "Append one human-reviewed marker.",
    ]

    first = subprocess.run(
        command,
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert first.returncode == 1
    assert "STATUS: needs-your-decision" in first.stdout
    assert log.read_text().splitlines() == ["plan", "write:single"]

    master, slave = pty.openpty()
    try:
        resumed = subprocess.Popen(
            command,
            cwd=repo,
            env=environment,
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(slave)
        os.write(master, b"y\nAccepted after inspecting the exact candidate.\n")
        stdout, stderr = resumed.communicate(timeout=30)
    finally:
        os.close(master)

    assert resumed.returncode == 0, (stdout, stderr)
    assert "STATUS: complete" in stdout
    assert log.read_text().splitlines() == ["plan", "write:single"]
    assert git(repo, "show", "HEAD:src/a.txt").endswith("small change")
