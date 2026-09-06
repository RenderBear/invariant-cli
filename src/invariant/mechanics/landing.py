from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.mechanics import audit, config, coordinate, git, governance, state
from invariant.mechanics.documents import dump_yaml, load_yaml


@dataclass(frozen=True)
class LandRequest:
    mode: str
    subject: str
    units: tuple[str, ...]
    scopes: tuple[str, ...]
    boundary: str
    merge_branch: str | None = None
    paths: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    governance_refs: tuple[str, ...] = ()
    reviewed: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    target: str | None = None
    plan: str | None = None
    allow_open: bool = False
    expected_tree: str | None = None


@dataclass(frozen=True)
class Candidate:
    commit: str
    tree: str
    target: str
    old: str | None
    unborn: bool
    covers: str | None
    reach_base: str | None


@dataclass(frozen=True)
class PushTarget:
    remote: str
    merge_ref: str

    @property
    def label(self) -> str:
        return f"{self.remote}/{self.merge_ref.removeprefix('refs/heads/')}"


def _validate_request(request: LandRequest) -> None:
    if request.mode not in {"direct", "staged", "merge"}:
        raise InvariantError(f"Invariant: invalid landing mode '{request.mode}'")
    if not request.units:
        raise InvariantError("Invariant: landing requires at least one unit id")
    if not request.scopes:
        raise InvariantError("Invariant: landing requires at least one scope")
    if request.mode == "direct" and not request.paths:
        raise InvariantError("Invariant: direct landing requires --paths")
    if request.boundary not in {"no-record", "recorded"} and not request.boundary.startswith("audit:"):
        raise InvariantError(f"Invariant: invalid --boundary-review '{request.boundary}'")
    if request.boundary.startswith("audit:") and not git.valid_id(request.boundary.removeprefix("audit:")):
        raise InvariantError(f"Invariant: invalid boundary audit id '{request.boundary.removeprefix('audit:')}'")
    if request.boundary == "recorded" and not request.governance_refs:
        raise InvariantError(
            "Invariant: --boundary-review recorded requires at least one --governance reference"
        )
    if request.mode == "merge" and not request.merge_branch:
        raise InvariantError("Invariant: merge landing requires a branch")
    if request.mode == "staged" and (
        request.boundary != "no-record"
        or request.domains
        or request.interfaces
        or request.governance_refs
        or request.reviewed
        or request.plan
        or request.allow_open
    ):
        raise InvariantError(
            "Invariant: staged landing is only for an explicit local no-record edit; use normal work-branch landing"
        )


def _last_attested(repo: Path, old: str) -> str | None:
    commits = git.run(["rev-list", "--first-parent", old], cwd=repo, check=False).stdout.splitlines()
    for commit in commits:
        if git.trailers(repo, commit, "Invariant-Boundary"):
            return commit
    return None


def _message(
    repo: Path,
    request: LandRequest,
    covers: str | None,
    candidate_tree: str,
) -> str:
    message = governance.commit_message(
        repo,
        request.subject,
        request.units,
        request.scopes,
        request.domains,
        request.plan,
    )
    message += f"Invariant-Boundary: {request.boundary}\n"
    if covers:
        message += f"Invariant-Covers: {covers}\n"
    for reference in request.governance_refs:
        message += f"Invariant-Governance: {reference}\n"
        if reference.startswith("semantic:"):
            identifier = reference.removeprefix("semantic:")
            digest = governance.semantic_record_digest(repo, identifier, candidate_tree)
            message += f"Invariant-Semantic: {identifier}@{digest}\n"
    for reference in request.reviewed:
        if reference.startswith("architecture:"):
            message += f"Invariant-Architecture: {reference}\n"
    return message


def _temporary_index(repo: Path) -> tuple[dict[str, str], Path]:
    descriptor, name = tempfile.mkstemp(prefix="invariant-index.")
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return {"GIT_INDEX_FILE": str(path)}, path


def _construct(repo: Path, request: LandRequest, target: str) -> Candidate:
    old = git.resolve(repo, f"refs/heads/{target}")
    unborn = old is None
    if unborn and git.resolve(repo, "HEAD"):
        raise InvariantError(f"Invariant: integration branch '{target}' has no commit")
    if request.mode == "merge" and unborn:
        raise InvariantError("Invariant: an unborn integration branch requires a direct first landing")
    if request.mode == "staged" and unborn:
        raise InvariantError("Invariant: staged landing requires an existing integration commit")
    if request.mode == "direct" and not unborn:
        raise InvariantError(
            "Invariant: direct landing is reserved for the first commit on an unborn integration branch; use a work branch and merge"
        )

    current = git.current_branch(repo)
    target_worktree = git.worktree_for_branch(repo, target)
    if request.mode == "direct":
        if current != target:
            raise InvariantError(
                f"Invariant: unborn direct landing must run in the integration worktree ('{target}')"
            )
        if git.run(["diff", "--cached", "--quiet", "--"], cwd=repo, check=False).returncode:
            raise InvariantError("Invariant: staged changes exist; preserve or unstage them before direct landing")
    elif request.mode == "staged":
        if current != target:
            raise InvariantError(
                f"Invariant: staged landing must run in the checked-out integration branch ('{target}')"
            )
        if git.run(["ls-files", "-u"], cwd=repo).stdout:
            raise InvariantError("Invariant: staged landing cannot include unresolved index entries")
        if git.run(["diff", "--cached", "--quiet", "--"], cwd=repo, check=False).returncode == 0:
            raise InvariantError("Invariant: staged landing requires staged changes")
    elif target_worktree and not git.tracked_worktree_clean(target_worktree):
        raise InvariantError(
            f"Invariant: integration worktree '{target_worktree}' has tracked changes; landing cannot synchronize it safely"
        )

    branch_ref: str | None = None
    if request.mode == "merge":
        branch_ref = git.resolve(repo, f"refs/heads/{request.merge_branch}")
        if not branch_ref:
            raise InvariantError(f"Invariant: merge branch '{request.merge_branch}' does not exist locally")
        candidate_worktree = git.worktree_for_branch(repo, str(request.merge_branch))
        if candidate_worktree and not git.tracked_worktree_clean(candidate_worktree):
            raise InvariantError(
                f"Invariant: candidate worktree '{candidate_worktree}' has uncommitted tracked changes"
            )

    covers: str | None = None
    reach_base = old
    if old:
        last = _last_attested(repo, old)
        if last and last != old:
            covers = f"{last}..{old}"
            reach_base = last
    if request.mode == "direct":
        environment, index = _temporary_index(repo)
        try:
            git.run(["read-tree", "--empty"], cwd=repo, env=environment)
            for path in request.paths:
                if Path(path).is_absolute() or ".." in Path(path).parts:
                    raise InvariantError(f"Invariant: invalid landing path '{path}'")
                git.run(["add", "-A", "--", path], cwd=repo, env=environment)
            tree = git.run(["write-tree"], cwd=repo, env=environment).stdout
        finally:
            index.unlink(missing_ok=True)
        parents: list[str] = []
    elif request.mode == "staged":
        assert old is not None
        tree = git.run(["write-tree"], cwd=repo).stdout
        if tree == git.resolve(repo, f"{old}^{{tree}}", ""):
            raise InvariantError("Invariant: staged index produces no change")
        parents = [old]
    else:
        assert old is not None and branch_ref is not None
        tree = git.merge_tree(repo, old, branch_ref)
        parents = [old, branch_ref]
    message = _message(repo, request, covers, tree)
    arguments = ["commit-tree", tree]
    for parent in parents:
        arguments.extend(["-p", parent])
    candidate = git.run(
        [*arguments, "-F", "-"], cwd=repo, input_text=message
    ).stdout
    return Candidate(candidate, tree, target, old, unborn, covers, reach_base)


def _remote_push_enabled(repo: Path, candidate: Candidate) -> bool:
    """Require accepted and proposed policy to opt in for this integration target."""
    if not candidate.old:
        return False
    accepted = config.resolve_at(repo, candidate.old, candidate.target)
    proposed = config.resolve_at(repo, candidate.commit, candidate.target)
    return (
        accepted.push_remote == "on"
        and proposed.push_remote == "on"
        and accepted.integration_branch == candidate.target
        and proposed.integration_branch == candidate.target
    )


def _remote_push_target(repo: Path, branch: str) -> PushTarget:
    remote_result = git.run(
        ["config", "--get", f"branch.{branch}.remote"], cwd=repo, check=False
    )
    merge_result = git.run(
        ["config", "--get", f"branch.{branch}.merge"], cwd=repo, check=False
    )
    remote_values = remote_result.stdout.splitlines() if remote_result.returncode == 0 else []
    merge_values = merge_result.stdout.splitlines() if merge_result.returncode == 0 else []
    if len(remote_values) != 1 or len(merge_values) != 1 or remote_values[0] == ".":
        raise Blocked(
            f"Invariant: push_remote is on but integration branch '{branch}' has no usable upstream",
            code="remote_upstream_missing",
            lines=[f"NEXT: configure an upstream for {branch}, or set push_remote off"],
        )
    remote = remote_values[0]
    merge_ref = merge_values[0]
    remotes = git.run(["remote"], cwd=repo).stdout.splitlines()
    if remote not in remotes or not merge_ref.startswith("refs/heads/"):
        raise Blocked(
            f"Invariant: push_remote is on but integration branch '{branch}' has no usable upstream",
            code="remote_upstream_missing",
            lines=[f"NEXT: configure an upstream for {branch}, or set push_remote off"],
        )
    if git.run(["check-ref-format", merge_ref], cwd=repo, check=False).returncode:
        raise Blocked(
            f"Invariant: upstream for integration branch '{branch}' has an invalid branch ref",
            code="remote_upstream_invalid",
        )
    return PushTarget(remote, merge_ref)


def _push_remote(repo: Path, candidate: Candidate, target: PushTarget) -> list[str]:
    refspec = f"{candidate.commit}:{target.merge_ref}"
    result = git.run(
        ["push", "--porcelain", "--", target.remote, refspec], cwd=repo, check=False
    )
    if result.returncode:
        details = [
            f"REMOTE: {line}"
            for line in [*result.stdout.splitlines(), *result.stderr.splitlines()]
            if line
        ]
        raise RemotePushFailed(
            "Invariant: remote push failed after local landing; the local integration commit is retained",
            lines=[
                f"PUSH: failed — {candidate.commit} -> {target.label}",
                *details,
                f"NEXT: resolve the remote condition; {candidate.commit} remains landed on {candidate.target}",
            ],
        )
    return [f"PUSHED: {candidate.commit} -> {target.label}"]


def prospective_tree(repo: Path, target: str, branch: str | None = None) -> str:
    """Return the exact prospective tree without creating a commit or moving a ref."""
    old = git.resolve(repo, f"refs/heads/{target}")
    if old is None:
        _, tree = audit.snapshot(repo)
        return tree
    if not branch:
        raise InvariantError("Invariant: a born integration target requires a candidate branch")
    branch_ref = git.resolve(repo, f"refs/heads/{branch}")
    if not branch_ref:
        raise InvariantError(f"Invariant: task branch '{branch}' is missing")
    return git.merge_tree(repo, old, branch_ref)


def _candidate_paths(repo: Path, candidate: Candidate) -> list[str]:
    if candidate.old:
        return git.changed_paths(repo, candidate.old, candidate.commit)
    return git.run(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", candidate.commit],
        cwd=repo,
    ).stdout.splitlines()


def _untracked_collisions(target_worktree: Path, candidate_paths: Iterable[str]) -> list[str]:
    untracked = git.run(["ls-files", "--others", "--"], cwd=target_worktree, check=False).stdout.splitlines()
    tracked = list(candidate_paths)
    collisions: list[str] = []
    for local in untracked:
        if any(governance.paths_related(local, candidate) for candidate in tracked):
            collisions.append(local)
    return collisions


def _checkout_safe(repo: Path, request: LandRequest, candidate: Candidate) -> None:
    current = git.resolve(repo, f"refs/heads/{candidate.target}")
    if current != candidate.old:
        raise Blocked(
            f"Invariant: integration branch changed during landing (expected {candidate.old}, current {current})",
            code="concurrent_ref_movement",
        )
    target_worktree = git.worktree_for_branch(repo, candidate.target)
    if request.mode == "staged":
        current_index = git.run(["write-tree"], cwd=repo).stdout
        if current_index != candidate.tree:
            raise InvariantError("Invariant: staged index changed during landing")
        return
    if request.mode == "direct" or not target_worktree:
        return
    if not git.tracked_worktree_clean(target_worktree):
        raise InvariantError(f"Invariant: integration worktree '{target_worktree}' changed during landing")
    collisions = _untracked_collisions(target_worktree, git.run(
        ["ls-tree", "-r", "--name-only", candidate.commit, "--"], cwd=repo
    ).stdout.splitlines())
    if collisions:
        raise InvariantError(
            "Invariant: untracked integration files collide with the candidate:",
            lines=[f"  {item}" for item in collisions],
            code="untracked_collision",
        )


def _governance_exists(repo: Path, reference: str) -> bool:
    if ":" not in reference:
        return False
    kind, identifier = reference.split(":", 1)
    if kind == "semantic":
        return identifier in {
            record.identifier
            for record in governance.semantic_records(repo)
            if record.status == "active"
        }
    if kind == "domain":
        return identifier in {str(row.get("id")) for row in governance.domains(repo)}
    if kind == "contract":
        return identifier in {str(row.get("id")) for row in governance.contracts(repo)}
    if kind == "constraint":
        return identifier in {str(row.get("id")) for row in governance.constraints(repo)}
    if kind == "architecture":
        path = identifier.split("#", 1)[0]
        if not (repo / path).is_file():
            return False
        return reference in {
            item
            for row in [*governance.domains(repo), *governance.contracts(repo)]
            for item in governance.architecture_refs(row.get("architecture"))
        }
    return False


@dataclass(frozen=True)
class ResolvedVerifier:
    command: tuple[str, ...]
    cwd: Path
    cwd_identity: str
    cache: str
    timeout: int
    identity: tuple[str, ...]


def _repository_path(repo: Path, value: str, label: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise Blocked(
            f"Invariant: {label} path '{value}' must stay inside the candidate repository",
            code="verification_failed",
        )
    candidate = repo / relative
    try:
        candidate.resolve().relative_to(repo.resolve())
    except (OSError, ValueError):
        raise Blocked(
            f"Invariant: {label} path '{value}' escapes the candidate repository",
            code="verification_failed",
        ) from None
    return candidate


def _python_test_command(repo: Path, spec: str) -> ResolvedVerifier:
    path, separator, selector = spec.partition("::")
    candidate = _repository_path(repo, path, "test verifier")
    workspace = candidate.parent
    while workspace != repo and not (workspace / "pyproject.toml").is_file():
        workspace = workspace.parent
    if not (workspace / "pyproject.toml").is_file():
        workspace = repo
    relative = candidate.relative_to(workspace).as_posix()
    selected = f"{relative}::{selector}" if separator else relative
    if (workspace / "uv.lock").is_file():
        command = ("uv", "run", "pytest", selected)
        runner = "uv-pytest"
        cache = "exact-tree"
    else:
        command = ("python3", "-m", "pytest", selected)
        runner = "python-pytest"
        cache = "never"
    return ResolvedVerifier(
        command,
        workspace,
        workspace.relative_to(repo).as_posix() or ".",
        cache,
        0,
        (runner, spec),
    )


def _resolve_verifier(repo: Path, locator: str, candidate_tree: Candidate) -> ResolvedVerifier:
    if locator.startswith("runner:"):
        value = locator.removeprefix("runner:")
        name, separator, target = value.partition("#")
        if not separator or not name or not target:
            raise Blocked(
                f"Invariant: runner verifier '{locator}' must use runner:<name>#<target>",
                code="verification_failed",
            )
        resolved = config.resolve_at(repo, candidate_tree.commit, candidate_tree.target)
        runner = resolved.verification.named(name)
        if runner is None:
            raise Blocked(
                f"Invariant: verifier runner '{name}' is not registered in .invariant/config.yml",
                code="verification_failed",
            )
        working = _repository_path(repo, runner.cwd, f"verifier runner '{name}' cwd")
        if not working.is_dir():
            raise Blocked(
                f"Invariant: verifier runner '{name}' cwd '{runner.cwd}' is absent from the candidate",
                code="verification_failed",
            )
        command = tuple(part.replace("{target}", target) for part in runner.command)
        return ResolvedVerifier(
            command,
            working,
            runner.cwd,
            runner.cache,
            runner.timeout,
            ("runner", name, target, *runner.command),
        )
    if locator.startswith("command:"):
        path = locator.removeprefix("command:")
        candidate = _repository_path(repo, path, "command verifier")
        if not candidate.is_file() or not candidate.stat().st_mode & 0o111:
            raise Blocked(
                f"Invariant: command verifier '{path}' is missing or not executable",
                code="verification_failed",
            )
        return ResolvedVerifier(
            (str(candidate),), repo, ".", "never", 0, ("command", path)
        )
    if locator.startswith("test:"):
        spec = locator.removeprefix("test:")
        path = spec.split("::", 1)[0]
        candidate = _repository_path(repo, path, "test verifier")
        if path.endswith(".sh"):
            return ResolvedVerifier(
                ("sh", path), repo, ".", "never", 0, ("shell-test", spec)
            )
        if path.endswith(".py"):
            return _python_test_command(repo, spec)
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return ResolvedVerifier(
                (str(candidate),), repo, ".", "never", 0, ("executable-test", spec)
            )
        raise Blocked(
            f"Invariant: test verifier '{locator}' is not directly executable; use a registered runner or command: wrapper",
            code="verification_failed",
        )
    if locator.startswith("schema:"):
        path = locator.removeprefix("schema:").split("#", 1)[0]
        candidate = _repository_path(repo, path, "schema verifier")
        if not candidate.is_file() or not candidate.stat().st_mode & 0o111:
            raise Blocked(
                f"Invariant: schema verifier '{locator}' needs a registered runner or executable command: wrapper",
                code="verification_failed",
            )
        return ResolvedVerifier(
            (str(candidate),), repo, ".", "never", 0, ("schema", locator)
        )
    if locator.startswith("contract:"):
        raise Blocked(
            f"Invariant: nested contract verifier '{locator}' must resolve to an executable verifier before landing",
            code="verification_failed",
        )
    raise Blocked(
        f"Invariant: unsupported check locator '{locator}'",
        code="verification_failed",
    )


def _executable_fingerprint(repo: Path, command: tuple[str, ...]) -> dict[str, object]:
    command_path = Path(command[0])
    try:
        return {"repository_path": command_path.resolve().relative_to(repo.resolve()).as_posix()}
    except (OSError, ValueError):
        pass
    executable = shutil.which(command[0]) or command[0]
    path = Path(executable)
    value: dict[str, object] = {"path": str(path)}
    try:
        stat = path.stat()
        value.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    except OSError:
        value["unresolved"] = True
    return value


def _verifier_mechanics_digest() -> str:
    digest = sha256()
    for name in ("landing.py", "config.py", "state.py", "governance.py"):
        path = Path(__file__).with_name(name)
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _verification_paths(repo: Path, key: str) -> tuple[Path, Path]:
    root = coordinate.ensure_runtime(repo) / "verifications"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{key}.yml", root / f"{key}.log"


def _run_locator(
    repo: Path, locator: str, candidate: Candidate
) -> tuple[list[str], bool, dict[str, object]]:
    output = [f"CHECK: running — {locator}"]
    resolved = _resolve_verifier(repo, locator, candidate)
    payload = {
        "protocol": 1,
        "tree": candidate.tree,
        "base": candidate.old or "unborn",
        "target": candidate.target,
        "locator": locator,
        "identity": list(resolved.identity),
        "cwd": resolved.cwd_identity,
        "command": list(resolved.command[1:]),
        "executable": _executable_fingerprint(repo, resolved.command),
        "platform": platform.platform(),
        "python": sys.version,
        "mechanics": _verifier_mechanics_digest(),
    }
    key = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt_path, log_path = _verification_paths(repo, key)
    if resolved.cache == "exact-tree" and receipt_path.is_file() and log_path.is_file():
        try:
            raw = load_yaml(receipt_path)
        except InvariantError:
            raw = None
        if isinstance(raw, dict) and raw.get("key") == key and raw.get("status") == "passed":
            return [f"CHECK: reused — {locator}", f"LOG: {log_path}"], True, raw
    if resolved.cache == "never":
        key = sha256(f"{key}\n{time.time_ns()}".encode()).hexdigest()
        receipt_path, log_path = _verification_paths(repo, key)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(resolved.command),
            cwd=resolved.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=resolved.timeout or None,
        )
    except subprocess.TimeoutExpired as exc:
        combined = "".join(
            value.decode() if isinstance(value, bytes) else (value or "")
            for value in (exc.stdout, exc.stderr)
        )
        log_path.write_text(combined, encoding="utf-8")
        timeout_payload = {
            **payload,
            "key": key,
            "evidence_id": f"verification:{key}",
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "failed",
            "exit_code": None,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output_digest": sha256(combined.encode()).hexdigest(),
            "log": str(log_path),
            "reusable": False,
            "failure": "timeout",
        }
        dump_yaml(receipt_path, timeout_payload)
        raise Blocked(
            f"Invariant: verifier timed out — {locator}",
            code="verification_failed",
            lines=[*output, *combined.rstrip("\n").splitlines(), f"LOG: {log_path}"],
        ) from exc
    combined = ""
    if completed.stdout:
        combined += completed.stdout
    if completed.stderr:
        combined += completed.stderr
    log_path.write_text(combined, encoding="utf-8")
    result_payload = {
        **payload,
        "key": key,
        "evidence_id": f"verification:{key}",
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "output_digest": sha256(combined.encode()).hexdigest(),
        "log": str(log_path),
        "reusable": resolved.cache == "exact-tree",
    }
    dump_yaml(receipt_path, result_payload)
    if completed.returncode:
        raise Blocked(
            f"Invariant: verifier failed — {locator}",
            code="verification_failed",
            lines=[*output, *combined.rstrip("\n").splitlines(), f"LOG: {log_path}"],
        )
    return [*output, f"CHECK: passed — {locator}", f"LOG: {log_path}"], False, result_payload


def _boundary_review(repo: Path, request: LandRequest, reach_lines: list[str]) -> list[str]:
    governance_changed = any(line.startswith("GOVERNANCE:") for line in reach_lines)
    if request.boundary == "no-record":
        if governance_changed:
            raise Blocked(
                "Invariant: governance changed; use --boundary-review recorded with --governance references",
                code="invalid_boundary",
            )
        return ["BOUNDARY-REVIEW: no-record"]
    if request.boundary.startswith("audit:"):
        if governance_changed:
            raise Blocked(
                "Invariant: governance changed; use --boundary-review recorded with --governance references",
                code="invalid_boundary",
            )
        identifier = request.boundary.removeprefix("audit:")
        path = repo / ".invariant" / "audits" / f"{identifier}.yml"
        if not path.is_file():
            raise Blocked(f"Invariant: boundary audit '{identifier}' is absent from the candidate")
        from invariant.mechanics.documents import load_yaml

        raw = load_yaml(path)
        if not isinstance(raw, dict) or raw.get("mode") != "scope":
            raise Blocked("Invariant: boundary review requires a scoped audit")
        unresolved = {"adoptable", "needs-authority", "needs-verifier"}
        if any(
            isinstance(item, dict) and item.get("disposition") in unresolved
            for item in raw.get("findings", [])
        ):
            raise Blocked(
                f"Invariant: boundary audit '{identifier}' has adoptable or unresolved findings"
            )
        audit.fresh(repo, identifier, "HEAD")
        return [f"BOUNDARY-REVIEW: audit:{identifier} — no governance adoption required"]
    for reference in request.governance_refs:
        if not _governance_exists(repo, reference):
            raise Blocked(
                f"Invariant: boundary governance '{reference}' is not an accepted candidate record"
            )
    return [f"BOUNDARY-REVIEW: recorded — {' '.join(request.governance_refs)}"]


def _coordinate_verify(repo: Path, request: LandRequest, candidate: Candidate) -> None:
    if not request.plan:
        return
    coordinate.validate_plan(repo, request.plan)
    lease_values: list[dict[str, object]] = []
    for unit in request.units:
        path = coordinate.runtime_root(repo) / "leases" / f"{unit}.yml"
        if not path.is_file():
            raise Blocked(f"Invariant: coordinated unit '{unit}' has no live lease")
        coordinate.lease_fresh(repo, unit)
        from invariant.mechanics.documents import load_yaml

        value = load_yaml(path)
        if not isinstance(value, dict):
            raise Blocked(f"Invariant: coordinated unit '{unit}' has an invalid lease")
        if value.get("integration_target") != candidate.target:
            raise Blocked(
                f"Invariant: lease '{unit}' targets '{value.get('integration_target')}', not '{candidate.target}'"
            )
        if request.mode == "merge" and value.get("branch") != request.merge_branch:
            raise Blocked(
                f"Invariant: lease '{unit}' belongs to '{value.get('branch')}', not '{request.merge_branch}'"
            )
        lease_values.append(value)
    for changed in _candidate_paths(repo, candidate):
        if not any(
            any(governance.paths_related(changed, claim) for claim in governance.refs(value.get("paths")))
            for value in lease_values
        ):
            raise Blocked(f"Invariant: coordinated path '{changed}' is outside the combined lease claims")
    for requested in request.interfaces:
        if not any(requested in governance.refs(value.get("interfaces")) for value in lease_values):
            raise Blocked(f"Invariant: interface '{requested}' is absent from the combined lease claims")
    for requested in request.domains:
        if not any(requested in governance.refs(value.get("domains")) for value in lease_values):
            raise Blocked(f"Invariant: domain '{requested}' is absent from the combined lease context")
    for requested in request.governance_refs:
        if not any(requested in governance.refs(value.get("governance")) for value in lease_values):
            raise Blocked(f"Invariant: governance '{requested}' is absent from the combined lease claims")


def collect_evidence(
    repo: Path, request: LandRequest
) -> tuple[Candidate, list[str], list[dict[str, object]]]:
    """Run exact-tree mechanical checks without authorizing or landing the candidate."""

    _validate_request(request)
    git.require_capabilities(repo)
    target = request.target or config.resolve(repo).integration_branch
    candidate = _construct(repo, request, target)
    _checkout_safe(repo, request, candidate)
    temporary = Path(tempfile.mkdtemp(prefix="invariant-evidence."))
    verify_dir = temporary / "verify"
    added = False
    lines: list[str] = []
    evidence: list[dict[str, object]] = []
    try:
        git.run(
            ["worktree", "add", "--quiet", "--detach", str(verify_dir), candidate.commit],
            cwd=repo,
        )
        added = True
        options = {
            "root_mode": candidate.unborn,
            "history": not candidate.unborn,
            "base": None if candidate.unborn else candidate.reach_base,
            "domains_selected": list(request.domains),
            "interfaces": list(request.interfaces),
        }
        reach_lines = governance.reach(verify_dir, **options)
        verifier_lines = governance.verifiers(verify_dir, **options)
        lines.extend(reach_lines)
        prior_target = os.environ.get("INVARIANT_INTEGRATION_TARGET")
        prior_unborn = os.environ.get("INVARIANT_ALLOW_UNBORN")
        os.environ["INVARIANT_INTEGRATION_TARGET"] = target
        os.environ["INVARIANT_ALLOW_UNBORN"] = "1" if candidate.unborn else "0"
        try:
            validation = state.validate(verify_dir)
        finally:
            if prior_target is None:
                os.environ.pop("INVARIANT_INTEGRATION_TARGET", None)
            else:
                os.environ["INVARIANT_INTEGRATION_TARGET"] = prior_target
            if prior_unborn is None:
                os.environ.pop("INVARIANT_ALLOW_UNBORN", None)
            else:
                os.environ["INVARIANT_ALLOW_UNBORN"] = prior_unborn
        if validation[-1] not in {
            "Invariant state valid",
            "no Invariant state — nothing to validate",
        }:
            raise Blocked(
                "Invariant: candidate state validation failed",
                code="invalid_state",
                lines=validation,
                data={"violations": validation},
            )
        snapshot = {
            "kind": "candidate_snapshot",
            "candidate_commit": candidate.commit,
            "tree": candidate.tree,
            "base": candidate.old or "unborn",
            "target": candidate.target,
            "changed_paths": _candidate_paths(verify_dir, candidate),
        }
        snapshot_id = sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        evidence.append({"evidence_id": f"candidate:{snapshot_id}", **snapshot})
        state_observation = {
            "kind": "state_validation",
            "candidate_commit": candidate.commit,
            "tree": candidate.tree,
            "validator": "invariant.state",
            "mechanics": _verifier_mechanics_digest(),
            "status": "passed",
        }
        state_id = sha256(
            json.dumps(state_observation, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        evidence.append({"evidence_id": f"state:{state_id}", **state_observation})
        executed: set[str] = set()
        for line in verifier_lines:
            if not line.startswith("VERIFY: "):
                continue
            locator = line.split(" ", 2)[2]
            if locator in executed:
                continue
            check_lines, _, record = _run_locator(verify_dir, locator, candidate)
            lines.extend(check_lines)
            evidence.append(record)
            executed.add(locator)
        for locator in request.checks:
            if locator in executed:
                continue
            check_lines, _, record = _run_locator(verify_dir, locator, candidate)
            lines.extend(check_lines)
            evidence.append(record)
            executed.add(locator)
        lines.append(f"EVIDENCE: {len(evidence)} exact-tree observation(s)")
        return candidate, lines, evidence
    finally:
        if added:
            git.run(["worktree", "remove", "--force", str(verify_dir)], cwd=repo, check=False)
        shutil.rmtree(temporary, ignore_errors=True)


def verify_and_land(repo: Path, request: LandRequest, *, update_ref: bool = True) -> list[str]:
    _validate_request(request)
    git.require_capabilities(repo)
    target = request.target or config.resolve(repo).integration_branch
    if git.run(["check-ref-format", "--branch", target], cwd=repo, check=False).returncode:
        raise InvariantError(f"Invariant: invalid integration branch '{target}'")
    candidate = _construct(repo, request, target)
    if request.expected_tree and candidate.tree != request.expected_tree:
        raise Blocked(
            "Invariant: candidate tree changed after its adapter review",
            code="stale_adapter_review",
            lines=[
                f"REVIEWED-TREE: {request.expected_tree}",
                f"CANDIDATE-TREE: {candidate.tree}",
            ],
        )
    push_target = (
        _remote_push_target(repo, target)
        if update_ref and _remote_push_enabled(repo, candidate)
        else None
    )
    _checkout_safe(repo, request, candidate)
    temporary = Path(tempfile.mkdtemp(prefix="invariant-land."))
    verify_dir = temporary / "verify"
    added = False
    output: list[str] = []
    try:
        git.run(["worktree", "add", "--quiet", "--detach", str(verify_dir), candidate.commit], cwd=repo)
        added = True
        if candidate.unborn:
            reach_lines = governance.reach(
                verify_dir,
                root_mode=True,
                domains_selected=list(request.domains),
                interfaces=list(request.interfaces),
            )
            verifier_lines = governance.verifiers(
                verify_dir,
                root_mode=True,
                domains_selected=list(request.domains),
                interfaces=list(request.interfaces),
            )
        else:
            reach_lines = governance.reach(
                verify_dir,
                base=candidate.reach_base,
                history=True,
                domains_selected=list(request.domains),
                interfaces=list(request.interfaces),
            )
            verifier_lines = governance.verifiers(
                verify_dir,
                base=candidate.reach_base,
                history=True,
                domains_selected=list(request.domains),
                interfaces=list(request.interfaces),
            )
        output.extend(reach_lines)
        if candidate.covers:
            output.append(f"COVERAGE: {candidate.covers}")
        verdict = next((line.removeprefix("REACH: ") for line in reach_lines if line.startswith("REACH: ")), "")
        if verdict in {"open", "gated"} and not request.allow_open:
            label = "open governance boundary" if verdict == "open" else "gated governance transition"
            raise Blocked(
                f"Invariant: {label} requires resolved authority (--allow-open)",
                code="authority_required",
                lines=output,
            )
        if request.mode == "staged" and verdict != "local":
            raise Blocked(
                f"Invariant: staged edit has {verdict} reach; use normal work-branch landing",
                lines=output,
            )
        prior_target = os.environ.get("INVARIANT_INTEGRATION_TARGET")
        prior_unborn = os.environ.get("INVARIANT_ALLOW_UNBORN")
        os.environ["INVARIANT_INTEGRATION_TARGET"] = target
        os.environ["INVARIANT_ALLOW_UNBORN"] = "1" if candidate.unborn else "0"
        try:
            state_lines = state.validate(verify_dir, landing=True)
        finally:
            if prior_target is None:
                os.environ.pop("INVARIANT_INTEGRATION_TARGET", None)
            else:
                os.environ["INVARIANT_INTEGRATION_TARGET"] = prior_target
            if prior_unborn is None:
                os.environ.pop("INVARIANT_ALLOW_UNBORN", None)
            else:
                os.environ["INVARIANT_ALLOW_UNBORN"] = prior_unborn
        if state_lines[-1] != "Invariant state valid" and state_lines[-1] != "no Invariant state — nothing to validate":
            raise Blocked(
                "Invariant: candidate state validation failed",
                code="invalid_state",
                lines=state_lines,
                data={"violations": state_lines},
            )
        governance.validate_trailer(verify_dir, candidate.commit)
        output.extend(_boundary_review(verify_dir, request, reach_lines))

        executed: set[str] = set()
        reused = 0
        for line in verifier_lines:
            if line.startswith("REVIEW: "):
                decision = line.split(" ", 2)[1]
                if decision not in request.reviewed:
                    raise Blocked(
                        f"Invariant: affected semantic {decision} requires --reviewed {decision} after prospective-tree review",
                        code="missing_review",
                        lines=output,
                    )
                output.append(f"REVIEW: accepted — {decision}")
            elif line.startswith("VERIFY: "):
                locator = line.split(" ", 2)[2]
                if locator not in executed:
                    check_lines, cache_hit, _ = _run_locator(verify_dir, locator, candidate)
                    output.extend(check_lines)
                    reused += int(cache_hit)
                    executed.add(locator)
        for locator in request.checks:
            if locator not in executed:
                check_lines, cache_hit, _ = _run_locator(verify_dir, locator, candidate)
                output.extend(check_lines)
                reused += int(cache_hit)
                executed.add(locator)
        output.append(f"CHECKS: {len(executed)} unique")
        if reused:
            output.append(f"CHECK-CACHE: {reused} reused")
        _coordinate_verify(verify_dir, request, candidate)

        if not update_ref:
            output.append(f"VERIFIED: {candidate.commit} ({candidate.tree})")
            return output
        _checkout_safe(repo, request, candidate)
        expected = candidate.old or "0" * 40
        git.run(["update-ref", f"refs/heads/{target}", candidate.commit, expected], cwd=repo)
        target_worktree = git.worktree_for_branch(repo, target)
        if target_worktree:
            if request.mode in {"direct", "staged"}:
                git.run(["read-tree", candidate.commit], cwd=target_worktree)
            else:
                git.run(["read-tree", "--reset", "-u", candidate.commit], cwd=target_worktree)
        for unit in request.units:
            lease = coordinate.runtime_root(repo) / "leases" / f"{unit}.yml"
            if lease.is_file():
                coordinate.release_lease(repo, unit)
        if request.plan:
            plan_path = coordinate.runtime_root(repo) / "plans" / f"{request.plan}.yml"
            if plan_path.is_file():
                plan_lines = coordinate.plan_status(repo, request.plan)
                active = any(
                    status in line
                    for line in plan_lines
                    for status in (" active ", " waiting ", " dispatchable ")
                )
                if not active:
                    plan_path.unlink()
        output.append(
            f"LANDED: {candidate.commit} -> {target} (prospective tree verified before ref update)"
        )
        if push_target:
            try:
                output.extend(_push_remote(repo, candidate, push_target))
            except RemotePushFailed as exc:
                exc.lines = [*output, *exc.lines]
                raise
        return output
    except Blocked as exc:
        if not exc.lines and output:
            exc.lines = output  # type: ignore[misc]
        raise
    finally:
        if added:
            git.run(["worktree", "remove", "--force", str(verify_dir)], cwd=repo, check=False)
        shutil.rmtree(temporary, ignore_errors=True)


def direct_edit(repo: Path, subject: str, unit: str, checks: Iterable[str], target: str | None = None) -> list[str]:
    if not git.valid_id(unit):
        raise InvariantError(f"Invariant: invalid unit id '{unit}'")
    target = target or config.resolve(repo).integration_branch
    if git.current_branch(repo) != target:
        raise InvariantError(
            f"Invariant: direct edit must run on the checked-out integration branch ('{target}')"
        )
    old = git.resolve(repo, "HEAD")
    if not old:
        raise InvariantError("Invariant: direct edit requires an existing integration commit")
    if git.run(["ls-files", "-u"], cwd=repo).stdout:
        raise InvariantError("Invariant: direct edit cannot include unresolved index entries")
    if git.run(["diff", "--cached", "--quiet", "--"], cwd=repo, check=False).returncode == 0:
        raise InvariantError("Invariant: direct edit requires staged changes")
    tree = git.run(["write-tree"], cwd=repo).stdout
    probe = git.run(
        ["commit-tree", tree, "-p", old, "-m", "Invariant direct-edit reach probe"], cwd=repo
    ).stdout
    temporary = Path(tempfile.mkdtemp(prefix="invariant-direct-edit."))
    verify_dir = temporary / "verify"
    try:
        git.run(["worktree", "add", "--quiet", "--detach", str(verify_dir), probe], cwd=repo)
        last = _last_attested(repo, old)
        base = last if last and last != old else old
        history = bool(last and last != old)
        reach_lines = governance.reach(verify_dir, base=base, history=history)
        verdict = next((line.removeprefix("REACH: ") for line in reach_lines if line.startswith("REACH: ")), "")
        if verdict != "local":
            raise Blocked(
                f"Invariant: direct edit has {verdict or 'unknown'} reach; use normal work-branch landing",
                lines=reach_lines,
            )
        scopes = tuple(line.removeprefix("TOPOLOGY: ") for line in reach_lines if line.startswith("TOPOLOGY: "))
        if not scopes:
            raise Blocked("Invariant: direct edit has no derived path scope; use normal work-branch landing")
    finally:
        git.run(["worktree", "remove", "--force", str(verify_dir)], cwd=repo, check=False)
        shutil.rmtree(temporary, ignore_errors=True)
    request = LandRequest(
        mode="staged",
        subject=subject,
        units=(unit,),
        scopes=scopes,
        boundary="no-record",
        checks=tuple(checks),
        target=target,
    )
    return [*reach_lines, *verify_and_land(repo, request)]
