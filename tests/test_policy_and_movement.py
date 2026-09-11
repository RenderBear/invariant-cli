"""Policy ownership, forged attestation, inert target movement, and record retirement."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from lifecycle_support import CLI
from lifecycle_support import begin as _begin
from lifecycle_support import codes as _codes
from lifecycle_support import git as _git
from lifecycle_support import invariant as _invariant
from lifecycle_support import repository as _repository

ARCHITECTURE = (
    "# Architecture\n\n## Source ownership {{#source-ownership}}\n\n{ownership}\n\n"
    "## Engine protocol {{#engine-protocol}}\n\n{protocol}\n"
)


def _governed_repository(path: Path) -> Path:
    """A repository with one accepted domain, contract, and semantic record, seeded pre-adoption."""

    repo = _repository(path)
    (repo / "docs").mkdir()
    (repo / "docs" / "architecture.md").write_text(
        ARCHITECTURE.format(ownership="The source module owns its value.", protocol="Engines accept requests.")
    )
    (repo / "src" / "engine.py").write_text("def run(): pass\n")
    (repo / "checks").mkdir()
    (repo / "checks" / "engine.sh").write_text("#!/bin/sh\nexit 0\n")
    (repo / "checks" / "engine.sh").chmod(0o755)
    records = repo / ".invariant" / "records"
    for kind in ("domain", "contract", "semantic"):
        (records / kind).mkdir(parents=True)
    (records / "domain" / "source.yml").write_text(
        "version: 1\nid: source\nresponsibility: Owns the source value.\n"
        "authority: user:task:seed#decision\n"
        "architecture: [architecture:docs/architecture.md#source-ownership]\n"
        "contracts: [source.engine.v1]\n"
    )
    (records / "contract" / "source.engine.v1.yml").write_text(
        "version: 1\nid: source.engine.v1\nassertion: Engines accept requests.\n"
        "authority: user:task:seed#decision\nbetween: [source, source]\n"
        "surfaces: [repo:src/engine.py]\n"
        "architecture: [architecture:docs/architecture.md#engine-protocol]\n"
        "verifies: [command:checks/engine.sh]\n"
    )
    (records / "semantic" / "source-owns-value.yml").write_text(
        "version: 1\nid: source-owns-value\n"
        "document: architecture:docs/architecture.md#source-ownership\n"
        "authority: user:task:seed#decision\nstatus: active\napplies_to: [repo:src]\n"
        "revisit_on: []\nverifies: []\nsupersedes: []\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "records")
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 0, payload
    return repo


def _implement(worktree: Path, files: dict[str, str | None]) -> None:
    for relative, content in files.items():
        target = worktree / relative
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "implement")


def _action(repo: Path, task: str, payload: dict) -> tuple[str, dict]:
    action = payload["result"]["task"]["actions"][0]["id"]
    code, detail = _invariant(repo, "task", "action", task, action)
    assert code == 0, detail
    return action, detail["result"]["action"]["context"]


def _respond(repo: Path, task: str, action: str, context: dict, *, authority: str, mode: str = "self-attested",
             effect: str | None = None, tree: str | None = None) -> tuple[int, dict]:
    review = {
        "version": 1,
        "review_id": context["review_id"],
        "candidate_tree": tree or context["candidate_tree"],
        "verdict": "accepted",
        "summary": "Accepted for the test.",
        "semantic_effect": effect or ("recorded" if context.get("governance") else "no-record"),
        "authority": authority,
        "review_mode": mode,
        "candidate_defects": [],
        "retained_discoveries": [],
    }
    path = repo.parent / f"{task}-{authority.replace(':', '-').replace('#', '-')}.json"
    path.write_text(json.dumps(review))
    return _invariant(repo, "task", "respond", task, action, "--input", str(path))


def _trailers(repo: Path, rev: str = "HEAD") -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for line in _git(repo, "log", "-1", "--format=%(trailers)", rev).splitlines():
        key, _, value = line.partition(": ")
        if key.startswith("Invariant-"):
            parsed.setdefault(key, []).append(value.strip())
    return parsed


# ------------------------------------------------------------------ policy ownership
def test_policy_change_lands_only_with_user_authority(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    config = (repo / ".invariant" / "config.yml").read_text()
    worktree = _begin(repo, "flip")
    _implement(worktree, {".invariant/config.yml": config.replace("push_remote: off", "push_remote: on")})
    before = _git(repo, "rev-parse", "main")

    code, payload = _invariant(repo, "task", "finish", "flip")
    assert code == 0 and payload["outcome"] == "needs_input", payload
    action, context = _action(repo, "flip", payload)
    assert context["policy_change"] is True

    code, payload = _respond(repo, "flip", action, context, authority="agent:codex", mode="independent")
    assert code == 1 and _codes(payload) == ["policy_review_required"], payload
    assert _git(repo, "rev-parse", "main") == before

    code, payload = _respond(repo, "flip", action, context, authority="user:task:flip#review")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    assert _trailers(repo)["Invariant-Review-Authority"] == ["user:task:flip#review"]
    assert "push_remote: on" in _git(repo, "show", "main:.invariant/config.yml")


def test_hand_committed_policy_is_covered_only_by_a_user_review(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    adoption = _begin(repo, "adopt")
    _implement(adoption, {"README.md": "adopted\n"})
    code, payload = _invariant(repo, "task", "finish", "adopt")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    config = repo / ".invariant" / "config.yml"
    config.write_text(config.read_text() + "verification:\n  timeout: 120\n")
    _git(repo, "commit", "-qam", "hand-edited policy")
    worktree = _begin(repo, "after")
    _implement(worktree, {"README.md": "after\n"})

    code, payload = _invariant(repo, "task", "finish", "after")
    assert payload["outcome"] == "needs_input", payload
    action, context = _action(repo, "after", payload)
    assert context["policy_change"] is True
    code, payload = _respond(repo, "after", action, context, authority="agent:codex", mode="independent")
    assert _codes(payload) == ["policy_review_required"], payload
    code, payload = _respond(repo, "after", action, context, authority="user:task:after#review")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    assert _trailers(repo)["Invariant-Covers"]


def test_set_commits_policy_with_user_provenance(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    code, payload = _invariant(repo, "set", "execution", "assisted")
    assert code == 0, payload
    commit = payload["result"]["policy_commit"]
    assert commit == _git(repo, "rev-parse", "HEAD")
    trailers = _trailers(repo)
    assert trailers["Invariant-Review-Authority"] == ["user:policy-execution"]
    assert _git(repo, "status", "--porcelain") == ""
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 0, payload
    code, payload = _invariant(repo, "set", "execution", "auto")
    assert code == 0 and payload["result"]["policy_commit"], payload
    # A later routine task lands without a policy review: the policy is already attested.
    worktree = _begin(repo, "routine")
    _implement(worktree, {"README.md": "x\n"})
    code, payload = _invariant(repo, "task", "finish", "routine")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    assert "Invariant-Covers" not in _trailers(repo)


# ------------------------------------------------------------------ forged attestation
def test_copied_trailers_do_not_make_a_hand_commit_a_landing(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    worktree = _begin(repo, "first")
    _implement(worktree, {"README.md": "first\n"})
    code, payload = _invariant(repo, "task", "finish", "first")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload

    (repo / "docs" / "architecture.md").write_text(
        ARCHITECTURE.format(ownership="Anyone may own the value.", protocol="Engines accept requests.")
    )
    parent = _git(repo, "rev-parse", "HEAD")
    _git(
        repo, "commit", "-qam", "quiet rewrite", "-m",
        f"Invariant-Unit: forged\nInvariant-Scope: area.root\nInvariant-Boundary: no-record\n"
        f"Invariant-Landing-Parent: {parent}",
    )
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 1 and _codes(payload) == ["invalid_state"], payload
    worktree = _begin(repo, "next")
    _implement(worktree, {"README.md": "next\n"})
    code, payload = _invariant(repo, "task", "finish", "next")
    assert code == 1 and "invalid_state" in _codes(payload), payload


# ------------------------------------------------------------------ inert movement
def test_accepted_review_survives_an_inert_landing(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    governed = _begin(repo, "governed")
    _implement(governed, {"src/feature.py": "FEATURE = 1\n"})
    code, payload = _invariant(repo, "task", "finish", "governed")
    assert payload["outcome"] == "needs_input", payload
    action, context = _action(repo, "governed", payload)
    reviewed_tree = context["candidate_tree"]

    other = _begin(repo, "other")
    _implement(other, {"README.md": "moved\n"})
    code, payload = _invariant(repo, "task", "finish", "other")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload

    code, payload = _respond(repo, "governed", action, context, authority="agent:codex")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    trailers = _trailers(repo)
    assert trailers["Invariant-Review-Tree"] == [reviewed_tree]
    assert _git(repo, "rev-parse", "HEAD^{tree}") != reviewed_tree
    assert _git(repo, "show", "main:README.md") == "moved"
    assert _git(repo, "show", "main:src/feature.py") == "FEATURE = 1"
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 0, payload


def test_review_is_restarted_when_movement_touches_affected_prose(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    governed = _begin(repo, "governed")
    _implement(governed, {"src/feature.py": "FEATURE = 1\n"})
    code, payload = _invariant(repo, "task", "finish", "governed")
    action, context = _action(repo, "governed", payload)

    other = _begin(repo, "other")
    _implement(
        other,
        {"docs/architecture.md": ARCHITECTURE.format(
            ownership="The source module owns its value.", protocol="Engines accept streams.")},
    )
    code, payload = _invariant(repo, "task", "finish", "other")
    other_action, other_context = _action(repo, "other", payload)
    code, payload = _respond(repo, "other", other_action, other_context, authority="user:task:other#review")
    assert payload["result"]["task"]["stage"] == "completed", payload

    code, payload = _respond(repo, "governed", action, context, authority="agent:codex")
    assert code == 1 and _codes(payload) == ["semantic_review_required"], payload
    code, payload = _invariant(repo, "task", "finish", "governed")
    assert payload["outcome"] == "needs_input", payload
    _, fresh = _action(repo, "governed", payload)
    assert fresh["candidate_tree"] != context["candidate_tree"]
    assert fresh["review_id"] != context["review_id"]


def test_public_change_retries_after_concurrent_movement(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    fake = tmp_path / "codex"
    fake.write_text(
        "#!/bin/sh\nset -eu\n"
        "if [ \"${1:-}\" = \"--version\" ]; then echo codex-fake; exit 0; fi\n"
        "if [ \"${1:-}\" = \"login\" ]; then echo 'Logged in'; exit 0; fi\n"
        "output=\nschema=false\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output-last-message\" ]; then shift; output=$1; fi\n"
        "  if [ \"$1\" = \"--output-schema\" ]; then schema=true; fi\n  shift\ndone\n"
        "request=$(cat)\n"
        "if [ \"$schema\" = true ]; then\n"
        "  case \"$request\" in\n"
        "    *'Request kind: task.respond'*)\n"
        "      review_id=$(printf '%s\\n' \"$request\" | sed -n 's/.*\"review_id\": \"\\([^\"]*\\)\".*/\\1/p' | head -n 1)\n"
        "      tree=$(printf '%s\\n' \"$request\" | sed -n 's/.*\"candidate_tree\": \"\\([^\"]*\\)\".*/\\1/p' | head -n 1)\n"
        "      printf '%s\\n' \"{\\\"version\\\":1,\\\"review_id\\\":\\\"$review_id\\\",\\\"candidate_tree\\\":\\\"$tree\\\",\\\"verdict\\\":\\\"accepted\\\",\\\"summary\\\":\\\"ok\\\",\\\"semantic_effect\\\":\\\"no-record\\\",\\\"authority\\\":\\\"agent:codex\\\",\\\"review_mode\\\":\\\"self-attested\\\",\\\"candidate_defects\\\":[],\\\"retained_discoveries\\\":[]}\" >\"$output\"\n"
        "      # Land an unrelated task while this review is pending: the target moves inertly.\n"
        f"      (cd '{repo}' && '{CLI}' task finish mover >/dev/null 2>&1 || true)\n"
        "      ;;\n"
        "    *) printf '%s\\n' '{\"strategy\":\"single\",\"summary\":\"one\",\"units\":[]}' >\"$output\" ;;\n"
        "  esac\n"
        "else\n"
        "  printf 'FEATURE = 2\\n' >src/feature.py\n  printf 'done\\n' >\"$output\"\n"
        "fi\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"t\"}'\n"
    )
    fake.chmod(0o755)
    mover = _begin(repo, "mover")
    _implement(mover, {"README.md": "mover\n"})
    completed = subprocess.run(
        [str(CLI), "--format", "json", "change", "--id", "moved-change", "Add a feature."],
        cwd=repo,
        env={**os.environ, "INVARIANT_CODEX": str(fake), "INVARIANT_HOME": str(tmp_path / "home"),
             "INVARIANT_DEFAULT_HARNESS": "codex"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, payload
    assert payload["result"]["status"] == "completed"
    assert _git(repo, "show", "main:README.md") == "mover"
    assert _git(repo, "show", "main:src/feature.py") == "FEATURE = 2"
    assert _trailers(repo).get("Invariant-Review-Tree")


def test_public_change_discards_provider_policy_edits(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    fake = tmp_path / "codex"
    fake.write_text(
        "#!/bin/sh\nset -eu\n"
        "if [ \"${1:-}\" = \"--version\" ]; then echo codex-fake; exit 0; fi\n"
        "if [ \"${1:-}\" = \"login\" ]; then echo 'Logged in'; exit 0; fi\n"
        "output=\nschema=false\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output-last-message\" ]; then shift; output=$1; fi\n"
        "  if [ \"$1\" = \"--output-schema\" ]; then schema=true; fi\n  shift\ndone\n"
        "cat >/dev/null\n"
        "if [ \"$schema\" = true ]; then printf '%s\\n' '{\"strategy\":\"single\",\"summary\":\"one\",\"units\":[]}' >\"$output\"\n"
        "else sed -i '' 's/push_remote: off/push_remote: on/' .invariant/config.yml; printf 'x\\n' >README.md; printf 'done\\n' >\"$output\"; fi\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"t\"}'\n"
    )
    fake.chmod(0o755)
    completed = subprocess.run(
        [str(CLI), "--format", "json", "change", "--id", "sneaky", "Flip publication on."],
        cwd=repo,
        env={**os.environ, "INVARIANT_CODEX": str(fake), "INVARIANT_HOME": str(tmp_path / "home"),
             "INVARIANT_DEFAULT_HARNESS": "codex"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, payload
    assert payload["result"]["policy_edits_discarded"] == 1
    assert "push_remote: off" in _git(repo, "show", "main:.invariant/config.yml")
    assert _git(repo, "show", "main:README.md") == "x"


# ------------------------------------------------------------------ retirement and typed refusals
def test_record_retirement_is_a_gated_landing(tmp_path: Path) -> None:
    repo = _governed_repository(tmp_path / "repo")
    code, payload = _invariant(
        repo, "task", "begin", "retire", "--goal", "retire the engine contract", "--domain", "source"
    )
    assert code == 0, payload
    worktree = Path(payload["result"]["task"]["work"]["worktree"])
    _implement(
        worktree,
        {
            ".invariant/records/contract/source.engine.v1.yml": None,
            ".invariant/records/domain/source.yml": (
                "version: 1\nid: source\nresponsibility: Owns the source value.\n"
                "authority: user:task:seed#decision\n"
                "architecture: [architecture:docs/architecture.md#source-ownership]\n"
                "contracts: []\n"
            ),
        },
    )
    code, payload = _invariant(repo, "task", "finish", "retire")
    assert code == 0 and payload["outcome"] == "needs_input", payload
    action, context = _action(repo, "retire", payload)
    assert context["review_requirement"] == "independent"
    assert "contract:source.engine.v1" in context["governance"]
    assert context["retired"] == ["contract:source.engine.v1"]
    code, payload = _respond(repo, "retire", action, context, authority="agent:codex", mode="independent",
                             effect="recorded")
    assert code == 0 and payload["result"]["task"]["stage"] == "completed", payload
    trailers = _trailers(repo)
    assert trailers["Invariant-Retired"] == ["contract:source.engine.v1"]
    assert "contract:source.engine.v1" in trailers["Invariant-Governance"]
    code, payload = _invariant(repo, "state", "validate", "--landing")
    assert code == 0, payload


def test_dirty_integration_checkout_is_a_typed_refusal(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    worktree = _begin(repo, "task")
    _implement(worktree, {"README.md": "x\n"})
    (repo / "src" / "a.txt").write_text("tampered\n")
    before = _git(repo, "rev-parse", "main")
    code, payload = _invariant(repo, "task", "finish", "task")
    assert code == 1 and _codes(payload) == ["dirty_integration_checkout"], payload
    assert _git(repo, "rev-parse", "main") == before


# ------------------------------------------------------------------ registration and presence
def test_init_registers_the_repository_and_nested_repositories(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-qb", "main")
    for name in ("user.name", "user.email"):
        _git(root, "config", name, "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("root\n")
    nested = root / "services" / "api"
    nested.mkdir(parents=True)
    _git(nested, "init", "-qb", "main")
    for name in ("user.name", "user.email"):
        _git(nested, "config", name, "t")
    _git(nested, "config", "commit.gpgsign", "false")
    (nested / "main.py").write_text("print('api')\n")
    _git(nested, "add", "-A")
    _git(nested, "commit", "-qm", "seed")
    (root / ".gitignore").write_text("services/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    home = tmp_path / "home"
    env = {**os.environ, "INVARIANT_HOME": str(home)}
    completed = subprocess.run(
        [str(CLI), "--format", "json", "init", "--defaults"], cwd=root, env=env, capture_output=True, text=True
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0, payload
    assert (nested / ".invariant" / "config.yml").is_file()
    assert _git(nested, "status", "--porcelain") == ""
    assert _trailers(nested)["Invariant-Review-Authority"] == ["user:initialization"]
    assert _trailers(root)["Invariant-Review-Authority"] == ["user:initialization"]
    listed = subprocess.run(
        [str(CLI), "--format", "json", "project", "list"], cwd=root, env=env, capture_output=True, text=True
    )
    paths = {item["path"] for item in json.loads(listed.stdout)["result"]["projects"]}
    assert paths == {str(root), str(nested)}
    assert "add" not in subprocess.run(
        [str(CLI), "project", "--help"], cwd=root, env=env, capture_output=True, text=True
    ).stdout.split("{")[1].split("}")[0].split(",")


def test_start_marks_its_session_live_for_the_workspace(tmp_path: Path) -> None:
    repo = _repository(tmp_path / "repo")
    home = tmp_path / "home"
    fake = tmp_path / "codex"
    fake.write_text(
        "#!/bin/sh\nset -eu\n"
        "if [ \"${1:-}\" = \"--version\" ]; then echo codex-fake; exit 0; fi\n"
        "if [ \"${1:-}\" = \"login\" ]; then echo 'Logged in'; exit 0; fi\n"
        "output=\nwhile [ \"$#\" -gt 0 ]; do if [ \"$1\" = \"--output-last-message\" ]; then shift; output=$1; fi; shift; done\n"
        "cat >/dev/null\nprintf '%s\\n' '{\"message\":\"hi\"}' >\"$output\"\n"
        "printf '%s\\n' '{\"type\":\"thread.started\",\"thread_id\":\"s\"}'\n"
    )
    fake.chmod(0o755)
    env = {**os.environ, "INVARIANT_HOME": str(home), "INVARIANT_CODEX": str(fake), "INVARIANT_DEFAULT_HARNESS": "codex"}
    created = subprocess.run(
        [str(CLI), "--format", "json", "session", "new", "Presence"], cwd=repo, env=env, capture_output=True, text=True
    )
    session_id = json.loads(created.stdout)["result"]["session"]["id"]
    process = subprocess.Popen(
        [str(CLI), "start", "--session", session_id], cwd=repo, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 10
        live = None
        while time.monotonic() < deadline and not live:
            completed = subprocess.run(
                [str(CLI), "--format", "json", "session", "show", session_id], cwd=repo, env=env,
                capture_output=True, text=True,
            )
            live = json.loads(completed.stdout)["result"]["session"].get("live")
            if not live:
                time.sleep(0.2)
        assert live and live["surface"] == "console" and live["pid"] == process.pid
    finally:
        process.stdin.close()
        process.wait(timeout=20)
    completed = subprocess.run(
        [str(CLI), "--format", "json", "session", "show", session_id], cwd=repo, env=env, capture_output=True, text=True
    )
    assert json.loads(completed.stdout)["result"]["session"]["live"] is None
