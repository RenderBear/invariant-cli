"""The human decisions of `invariant establish` as they appear in a terminal."""

from __future__ import annotations

from pathlib import Path

from lifecycle_support import git, invariant, repository
from test_terminal_presentation import _tty


def _fake_codex(path: Path) -> Path:
    executable = path / "codex"
    executable.write_text(
        r"""#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli establish-test'
  exit 0
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  echo 'Logged in using test account'
  exit 0
fi
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output=$1
  fi
  shift
done
[ -n "$output" ] || exit 3
request=$(cat)
task=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"task": "\([^"]*\)",*$/\1/p' | head -n 1)
cat >"$output" <<JSON
{"version":1,"findings":[
 {"id":"source-ownership","summary":"The src tree is the application's only implementation surface and nothing else writes to it.","evidence":["repo:src/a.txt"],"proposed":"domain","disposition":"adoptable","authority":"user:task:$task#audit",
  "records":[{"kind":"domain","value":{"id":"source","responsibility":"Owns the application source.","authority":"user:task:$task#audit","parent":null,"architecture":[],"contracts":[]}}]}
]}
JSON
printf '%s\n' '{"type":"thread.started","thread_id":"establish-session"}'
printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}'
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _human_repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = repository(tmp_path / "repo")
    code, _ = invariant(repo, "set", "authority", "human")
    assert code == 0
    git(repo, "commit", "-qam", "human authority")
    environment = {
        "INVARIANT_CODEX": str(_fake_codex(tmp_path)),
        "INVARIANT_HOME": str(tmp_path / "invariant-home"),
    }
    return repo, environment


def test_declining_the_proposal_is_a_neutral_outcome(tmp_path: Path) -> None:
    repo, environment = _human_repository(tmp_path)
    code, output = _tty(
        repo,
        ["establish", "--using", "codex"],
        environment=environment,
        input_steps=[
            ("Record all, none, or selected numbers", "all\n"),
            ("Accept this proposal?", "n\n"),
        ],
    )

    assert code == 0, output
    # The proposal names what it changes before asking for acceptance.
    assert output.index("Records") < output.index("domain:source") < output.index("Accept this proposal?")
    assert ".invariant/DOMAINS.yml" in output
    assert "not accepted" in output
    assert "×" not in output
    assert "invariant establish --discard" in output
    assert "interactive terminal" not in output


def test_accepting_the_proposal_lands_it(tmp_path: Path) -> None:
    repo, environment = _human_repository(tmp_path)
    _tty(
        repo,
        ["establish", "--using", "codex"],
        environment=environment,
        input_steps=[
            ("Record all, none, or selected numbers", "all\n"),
            ("Accept this proposal?", "n\n"),
        ],
    )
    code, output = _tty(
        repo,
        ["establish", "--using", "codex"],
        environment=environment,
        input_steps=[("Accept this proposal?", "y\n"), ("Reason (optional)", "\n")],
    )

    assert code == 0, output
    assert "Records established" in output
    assert "domain:source" in output
    assert "id: source" in (repo / ".invariant" / "DOMAINS.yml").read_text()
