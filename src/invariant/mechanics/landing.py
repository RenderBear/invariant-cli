from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import ContextManager, Iterable, Iterator

from invariant.errors import Blocked, InvariantError, RemotePushFailed
from invariant.mechanics import audit, config, coordinate, git, governance, state
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.protocol import BoundaryDisposition, BoundaryKind, Evidence, Reach


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
    review_authority: str | None = None
    review_mode: str | None = None
    review_digest: str | None = None


@dataclass(frozen=True)
class Candidate:
    commit: str
    tree: str
    target: str
    old: str | None
    unborn: bool
    covers: str | None
    reach_base: str | None


ROUTINE_CONVERGENCE_ATTEMPTS = 16


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
    for unit in request.units:
        if not git.valid_id(unit):
            raise InvariantError(f"Invariant: invalid landing unit '{unit}'")
    if not request.subject.strip() or "\n" in request.subject or "\r" in request.subject:
        raise InvariantError("Invariant: landing subject must be one non-empty line")
    if not request.scopes:
        raise InvariantError("Invariant: landing requires at least one scope")
    if request.mode == "direct" and not request.paths:
        raise InvariantError("Invariant: direct landing requires --paths")
    try:
        boundary = BoundaryDisposition.parse(
            request.boundary, allow_unresolved=False
        )
    except InvariantError as exc:
        raise InvariantError(
            f"Invariant: invalid --boundary-review '{request.boundary}'"
        ) from exc
    if boundary.kind == BoundaryKind.RECORDED and not request.governance_refs:
        raise InvariantError(
            "Invariant: --boundary-review recorded requires at least one --governance reference"
        )
    review_values = (
        request.review_authority,
        request.review_mode,
        request.review_digest,
    )
    if any(review_values) and not all(review_values):
        raise InvariantError(
            "Invariant: review authority, mode, and digest must be supplied together"
        )
    if request.review_mode and request.review_mode not in {"self-attested", "independent"}:
        raise InvariantError("Invariant: review mode must be self-attested or independent")
    if request.review_authority and any(
        character in request.review_authority for character in "\r\n"
    ):
        raise InvariantError("Invariant: review authority must be one line")
    if request.review_digest and not re.fullmatch(r"[0-9a-f]{64}", request.review_digest):
        raise InvariantError("Invariant: review digest must be a SHA-256 value")
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
    for commit in git.commits_mentioning(repo, old, "Invariant-Boundary"):
        if git.trailers(repo, commit, "Invariant-Boundary"):
            return commit
    return None


def _message(
    repo: Path,
    request: LandRequest,
    covers: str | None,
    candidate_tree: str,
    landing_parent: str | None,
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
    message += f"Invariant-Landing-Parent: {landing_parent or 'unborn'}\n"
    if covers:
        message += f"Invariant-Covers: {covers}\n"
    semantic_refs = [
        reference.removeprefix("semantic:")
        for reference in request.governance_refs
        if reference.startswith("semantic:")
    ]
    semantic_records = (
        {
            record.identifier: record
            for record in governance.semantic_records(repo, candidate_tree)
        }
        if semantic_refs
        else {}
    )
    content_cache: dict[str, str] = {}
    for reference in request.governance_refs:
        message += f"Invariant-Governance: {reference}\n"
        if reference.startswith("semantic:"):
            identifier = reference.removeprefix("semantic:")
            record = semantic_records.get(identifier)
            if record is None:
                raise InvariantError(
                    f"Invariant: unknown semantic record '{identifier}'"
                )
            digest = governance.digest_semantic_record(
                repo, record, candidate_tree, content_cache
            )
            message += f"Invariant-Semantic: {identifier}@{digest}\n"
    for reference in request.reviewed:
        if reference.startswith("architecture:"):
            message += f"Invariant-Architecture: {reference}\n"
    if request.review_authority:
        message += f"Invariant-Review-Authority: {request.review_authority}\n"
        message += f"Invariant-Review-Mode: {request.review_mode}\n"
        message += f"Invariant-Review-Digest: {request.review_digest}\n"
    return message


def _temporary_index(repo: Path) -> tuple[dict[str, str], Path]:
    descriptor, name = tempfile.mkstemp(prefix="invariant-index.")
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return {"GIT_INDEX_FILE": str(path)}, path


def _journal_path(repo: Path, target: str) -> Path:
    return coordinate.runtime_root(repo) / "landing" / f"{target.replace('/', '%')}.yml"


def _lock_path(repo: Path, target: str, purpose: str) -> Path:
    root = coordinate.ensure_runtime(repo) / "landing"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{target.replace('/', '%')}.{purpose}.lock"


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold one process lock without leaving stale ownership after a crash."""

    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _landing_lock(repo: Path, target: str) -> ContextManager[None]:
    return _file_lock(_lock_path(repo, target, "transaction"))


def _convergence_lock(repo: Path, target: str) -> ContextManager[None]:
    return _file_lock(_lock_path(repo, target, "convergence"))


def convergence_queue(repo: Path, target: str) -> ContextManager[None]:
    """Serialize exact-tree rebuilds after otherwise safe concurrent movement."""

    return _convergence_lock(repo, target)


def _sync_checkout(target_worktree: Path, commit: str, mode: str) -> None:
    if mode in {"direct", "staged"}:
        git.run(["read-tree", commit], cwd=target_worktree)
    else:
        git.run(["read-tree", "--reset", "-u", commit], cwd=target_worktree)


def replay_pending_sync(repo: Path, target: str) -> list[str]:
    """Finish an integration checkout sync that a crash interrupted after the ref moved."""

    with _landing_lock(repo, target):
        return _replay_pending_sync_locked(repo, target)


def _replay_pending_sync_locked(repo: Path, target: str) -> list[str]:
    """Replay a pending sync while the target landing transaction is held."""

    journal = _journal_path(repo, target)
    if not journal.is_file():
        return []
    raw = load_yaml(journal)
    commit = str(raw.get("commit") or "") if isinstance(raw, dict) else ""
    previous = str(raw.get("previous") or "") if isinstance(raw, dict) else ""
    mode = str(raw.get("mode") or "merge") if isinstance(raw, dict) else "merge"
    current = git.resolve(repo, f"refs/heads/{target}")
    target_worktree = git.worktree_for_branch(repo, target)
    if not commit or current != commit or target_worktree is None:
        journal.unlink(missing_ok=True)
        return []
    index_tree = git.run(["write-tree"], cwd=target_worktree, check=False)
    landed_tree = git.resolve(repo, f"{commit}^{{tree}}", "")
    if index_tree.returncode == 0 and index_tree.stdout == landed_tree:
        journal.unlink(missing_ok=True)
        return []
    previous_tree = git.resolve(repo, f"{previous}^{{tree}}", "") if previous != "unborn" else None
    untouched = (
        index_tree.returncode == 0
        and index_tree.stdout == previous_tree
        and git.run(["diff", "--quiet", "--"], cwd=target_worktree, check=False).returncode == 0
    )
    if not untouched:
        raise Blocked(
            f"Invariant: integration worktree '{target_worktree}' was edited after an interrupted landing sync",
            code="landing_sync_conflict",
            lines=[
                f"LANDED: {commit}",
                f"NEXT: restore the checkout with 'git -C {target_worktree} read-tree --reset -u {commit}', then remove {journal}",
            ],
        )
    _sync_checkout(target_worktree, commit, mode)
    journal.unlink(missing_ok=True)
    return [f"SYNCED: {target_worktree} to {commit} after an interrupted landing"]


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
    message = _message(repo, request, covers, tree, old)
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


def _untracked_collisions(
    repo: Path,
    target_worktree: Path,
    candidate_commit: str,
    candidate_paths: Iterable[str],
) -> list[str]:
    untracked = git.run(["ls-files", "--others", "--"], cwd=target_worktree, check=False).stdout.splitlines()
    tracked = list(candidate_paths)
    collisions: list[str] = []
    for local in untracked:
        related = [
            candidate
            for candidate in tracked
            if governance.paths_related(local, candidate)
        ]
        if not related:
            continue
        local_path = target_worktree / local
        if related == [local] and not local_path.is_symlink():
            local_blob = git.run(
                ["hash-object", "--", local], cwd=target_worktree, check=False
            ).stdout
            candidate_entry = git.run(
                ["ls-tree", candidate_commit, "--", local], cwd=repo, check=False
            ).stdout
            fields = candidate_entry.split(None, 3)
            candidate_mode = fields[0] if len(fields) == 4 else ""
            candidate_blob = fields[2] if len(fields) == 4 else ""
            local_mode = "100755" if local_path.stat().st_mode & 0o111 else "100644"
            if (
                local_blob
                and local_blob == candidate_blob
                and local_mode == candidate_mode
            ):
                continue
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
    collisions = _untracked_collisions(
        repo,
        target_worktree,
        candidate.commit,
        git.run(
            ["ls-tree", "-r", "--name-only", candidate.commit, "--"], cwd=repo
        ).stdout.splitlines(),
    )
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
        return identifier in governance.domain_index(repo).identifiers
    if kind == "contract":
        return identifier in {str(row.get("id")) for row in governance.contracts(repo)}
    if kind == "constraint":
        return identifier in {str(row.get("id")) for row in governance.constraints(repo)}
    if kind == "architecture":
        path = identifier.split("#", 1)[0]
        if not (repo / path).is_file():
            return False
        registered = {
            item
            for domain in governance.domains(repo)
            for item in domain.architecture
        }
        registered.update(
            item
            for row in governance.contracts(repo)
            for item in governance.architecture_refs(row.get("architecture"))
        )
        registered.update(
            record.document
            for record in governance.semantic_records(repo)
            if record.status == "active"
        )
        return reference in registered
    return False


@dataclass(frozen=True)
class ResolvedVerifier:
    command: tuple[str, ...]
    cwd: Path
    cwd_identity: str
    cache: str
    timeout: int
    identity: tuple[str, ...]


BUILTIN_VERIFIER_TIMEOUT = 300


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


def _nearest_project(repo: Path, candidate: Path, marker: str) -> Path | None:
    workspace = candidate.parent
    while True:
        if (workspace / marker).is_file():
            return workspace
        if workspace == repo:
            return None
        workspace = workspace.parent


def _python_test_command(repo: Path, spec: str) -> ResolvedVerifier:
    path, separator, selector = spec.partition("::")
    candidate = _repository_path(repo, path, "test verifier")
    workspace = _nearest_project(repo, candidate, "pyproject.toml") or repo
    relative = candidate.relative_to(workspace).as_posix()
    selected = f"{relative}::{selector}" if separator else relative
    if (workspace / "uv.lock").is_file():
        command = ("uv", "run", "--frozen", "pytest", selected)
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
        BUILTIN_VERIFIER_TIMEOUT,
        (runner, spec),
    )


def _shell_test_command(repo: Path, spec: str) -> ResolvedVerifier:
    path, separator, _ = spec.partition("::")
    if separator:
        raise Blocked(
            f"Invariant: shell test verifier 'test:{spec}' cannot use a test selector",
            code="verification_failed",
        )
    candidate = _repository_path(repo, path, "test verifier")
    workspace = _nearest_project(repo, candidate, "pyproject.toml")
    if workspace is not None and (workspace / "uv.lock").is_file():
        relative = candidate.relative_to(workspace).as_posix()
        return ResolvedVerifier(
            ("uv", "run", "--frozen", "sh", relative),
            workspace,
            workspace.relative_to(repo).as_posix() or ".",
            "exact-tree",
            BUILTIN_VERIFIER_TIMEOUT,
            ("uv-shell-test", spec),
        )
    return ResolvedVerifier(
        ("sh", path),
        repo,
        ".",
        "never",
        BUILTIN_VERIFIER_TIMEOUT,
        ("shell-test", spec),
    )


def _resolve_verifier(repo: Path, locator: str, candidate_tree: Candidate) -> ResolvedVerifier:
    resolved = _resolve_verifier_command(repo, locator, candidate_tree)
    if resolved.timeout:
        return resolved
    # A verifier without its own limit still gets the repository default; a hung check must
    # never hold the landing open indefinitely.
    settings = config.resolve_at(repo, candidate_tree.commit, candidate_tree.target)
    return replace(resolved, timeout=settings.verification.timeout)


def _resolve_verifier_command(
    repo: Path, locator: str, candidate_tree: Candidate
) -> ResolvedVerifier:
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
            return _shell_test_command(repo, spec)
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


def _verification_environment(command: tuple[str, ...]) -> dict[str, str]:
    environment = os.environ.copy()
    if command[:2] == ("uv", "run"):
        # A verifier executes from an exact candidate worktree. Reusing the parent command's
        # project environment can make uv wait on or silently select a different checkout's
        # environment, especially when Invariant itself was launched through `uv run`.
        environment.pop("VIRTUAL_ENV", None)
        environment.pop("UV_PROJECT_ENVIRONMENT", None)
    return environment


def _run_locator(
    repo: Path, locator: str, candidate: Candidate
) -> tuple[list[str], bool, dict[str, object]]:
    output = [f"CHECK: running — {locator}"]
    resolved = _resolve_verifier(repo, locator, candidate)
    payload = {
        "protocol": 1,
        "kind": "verification",
        "tree": candidate.tree,
        "base": candidate.old or "unborn",
        "target": candidate.target,
        "locator": locator,
        "identity": list(resolved.identity),
        "cwd": resolved.cwd_identity,
        "command": list(resolved.command),
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
            return (
                [f"CHECK: reused — {locator}", f"LOG: {log_path}"],
                True,
                {**raw, "kind": str(raw.get("kind") or "verification")},
            )
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
            env=_verification_environment(resolved.command),
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
            lines=[
                f"CHECK: timed out after {resolved.timeout}s — {locator}",
                *combined.rstrip("\n").splitlines(),
                f"LOG: {log_path}",
            ],
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
            lines=[
                f"CHECK: failed with exit {completed.returncode} — {locator}",
                *combined.rstrip("\n").splitlines(),
                f"LOG: {log_path}",
            ],
        )
    return [*output, f"CHECK: passed — {locator}", f"LOG: {log_path}"], False, result_payload


def _boundary_review(repo: Path, request: LandRequest, reach_lines: list[str]) -> list[str]:
    governance_changed = any(line.startswith("GOVERNANCE:") for line in reach_lines)
    boundary = BoundaryDisposition.parse(request.boundary, allow_unresolved=False)
    if boundary.kind == BoundaryKind.NO_RECORD:
        if governance_changed:
            raise Blocked(
                "Invariant: governance changed; use --boundary-review recorded with --governance references",
                code="invalid_boundary",
            )
        return ["BOUNDARY-REVIEW: no-record"]
    if boundary.kind == BoundaryKind.AUDIT:
        if governance_changed:
            raise Blocked(
                "Invariant: governance changed; use --boundary-review recorded with --governance references",
                code="invalid_boundary",
            )
        identifier = str(boundary.audit_id)
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
) -> tuple[Candidate, list[str], list[Evidence], governance.ContextResult]:
    """Run exact-tree mechanical checks without authorizing or landing the candidate."""

    _validate_request(request)
    git.require_capabilities(repo)
    target = request.target or config.resolve(repo).integration_branch
    with _landing_lock(repo, target):
        _replay_pending_sync_locked(repo, target)
        candidate = _construct(repo, request, target)
        _checkout_safe(repo, request, candidate)
    temporary = Path(tempfile.mkdtemp(prefix="invariant-evidence."))
    verify_dir = temporary / "verify"
    added = False
    lines: list[str] = []
    evidence: list[Evidence] = []
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
        candidate_context = governance.context_result(verify_dir, **options)
        lines.extend(candidate_context.lines)
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
        evidence.append(
            Evidence.from_mapping(
                {"evidence_id": f"candidate:{snapshot_id}", **snapshot}
            )
        )
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
        evidence.append(
            Evidence.from_mapping(
                {"evidence_id": f"state:{state_id}", **state_observation}
            )
        )
        executed: set[str] = set()
        for locator in candidate_context.verifier_locators:
            if locator in executed:
                continue
            check_lines, _, record = _run_locator(verify_dir, locator, candidate)
            lines.extend(check_lines)
            evidence.append(Evidence.from_mapping(record))
            executed.add(locator)
        for locator in request.checks:
            if locator in executed:
                continue
            check_lines, _, record = _run_locator(verify_dir, locator, candidate)
            lines.extend(check_lines)
            evidence.append(Evidence.from_mapping(record))
            executed.add(locator)
        lines.append(f"EVIDENCE: {len(evidence)} exact-tree observation(s)")
        return candidate, lines, evidence, candidate_context
    finally:
        if added:
            git.run(["worktree", "remove", "--force", str(verify_dir)], cwd=repo, check=False)
        shutil.rmtree(temporary, ignore_errors=True)


def _routine_convergence_allowed(request: LandRequest, update_ref: bool) -> bool:
    return (
        update_ref
        and request.mode == "merge"
        and request.boundary == "no-record"
        and not request.domains
        and not request.interfaces
        and not request.governance_refs
        and not request.reviewed
        and not request.allow_open
        and not request.expected_tree
    )


def verify_and_land(repo: Path, request: LandRequest, *, update_ref: bool = True) -> list[str]:
    _validate_request(request)
    if (request.boundary == "recorded" or request.reviewed) and not request.review_authority:
        raise Blocked(
            "Invariant: reviewed semantic change is missing durable review provenance",
            code="missing_review",
        )
    git.require_capabilities(repo)
    target = request.target or config.resolve(repo).integration_branch
    if git.run(["check-ref-format", "--branch", target], cwd=repo, check=False).returncode:
        raise InvariantError(f"Invariant: invalid integration branch '{target}'")

    try:
        return _verify_and_land_once(repo, request, target, update_ref=update_ref)
    except Blocked as movement:
        if (
            movement.code != "concurrent_ref_movement"
            or not _routine_convergence_allowed(request, update_ref)
        ):
            raise
        initial_movement = movement

    last_movement = initial_movement
    with _convergence_lock(repo, target):
        for attempt in range(1, ROUTINE_CONVERGENCE_ATTEMPTS + 1):
            try:
                output = _verify_and_land_once(repo, request, target, update_ref=update_ref)
            except Blocked as movement:
                if movement.code != "concurrent_ref_movement":
                    raise
                last_movement = movement
                continue
            return [
                f"CONVERGENCE: rebuilt and reverified after concurrent movement ({attempt} retry)",
                *output,
            ]
    raise last_movement


def _verify_and_land_once(
    repo: Path,
    request: LandRequest,
    target: str,
    *,
    update_ref: bool,
) -> list[str]:
    with _landing_lock(repo, target):
        _replay_pending_sync_locked(repo, target)
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
        _checkout_safe(repo, request, candidate)
    push_target = (
        _remote_push_target(repo, target)
        if update_ref and _remote_push_enabled(repo, candidate)
        else None
    )
    temporary = Path(tempfile.mkdtemp(prefix="invariant-land."))
    verify_dir = temporary / "verify"
    added = False
    output: list[str] = []
    try:
        git.run(["worktree", "add", "--quiet", "--detach", str(verify_dir), candidate.commit], cwd=repo)
        added = True
        candidate_context = governance.context_result(
            verify_dir,
            root_mode=candidate.unborn,
            base=None if candidate.unborn else candidate.reach_base,
            history=not candidate.unborn,
            domains_selected=list(request.domains),
            interfaces=list(request.interfaces),
        )
        reach_lines = candidate_context.lines
        output.extend(reach_lines)
        if candidate.covers:
            output.append(f"COVERAGE: {candidate.covers}")
        verdict = candidate_context.reach
        independent_required = (
            verdict == Reach.GATED
            or any(
                item.kind == "contract" and item.level == Reach.OPEN
                for item in candidate_context.affected
            )
        )
        if independent_required and not (
            str(request.review_authority or "").startswith("user:")
            or request.review_mode == "independent"
        ):
            raise Blocked(
                "Invariant: gated governance and contract-defining changes require a human or independent review",
                code="independent_review_required",
                lines=output,
            )
        if verdict.needs_explicit_authority and not request.allow_open:
            label = (
                "open governance boundary"
                if verdict == Reach.OPEN
                else "gated governance transition"
            )
            raise Blocked(
                f"Invariant: {label} requires resolved authority (--allow-open)",
                code="authority_required",
                lines=output,
            )
        if request.mode == "staged" and verdict != Reach.LOCAL:
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
        for decision in candidate_context.reviews:
            if decision not in request.reviewed:
                raise Blocked(
                    f"Invariant: affected semantic {decision} requires --reviewed {decision} after prospective-tree review",
                    code="missing_review",
                    lines=output,
                )
            output.append(f"REVIEW: accepted — {decision}")
        for locator in candidate_context.verifier_locators:
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
        with _landing_lock(repo, target):
            _replay_pending_sync_locked(repo, target)
            _checkout_safe(repo, request, candidate)
            expected = candidate.old or "0" * 40
            journal = _journal_path(repo, target)
            dump_yaml(
                journal,
                {
                    "version": 1,
                    "target": target,
                    "commit": candidate.commit,
                    "previous": candidate.old or "unborn",
                    "mode": request.mode,
                },
            )
            updated = git.run(
                ["update-ref", f"refs/heads/{target}", candidate.commit, expected],
                cwd=repo,
                check=False,
            )
            if updated.returncode:
                journal.unlink(missing_ok=True)
                current = git.resolve(repo, f"refs/heads/{target}")
                if current != candidate.old:
                    raise Blocked(
                        f"Invariant: integration branch '{target}' advanced during verification; integration branch unchanged",
                        code="concurrent_ref_movement",
                        lines=[
                            *output,
                            f"EXPECTED-HEAD: {candidate.old or 'unborn'}",
                            f"ACTUAL-HEAD: {current or 'unborn'}",
                            "NEXT: rerun the landing; the candidate is reverified against the advanced head",
                        ],
                    )
                raise InvariantError(
                    f"Invariant: {updated.stderr or updated.stdout or 'Git command failed'}",
                    code="git_failed",
                )
            target_worktree = git.worktree_for_branch(repo, target)
            if target_worktree:
                _sync_checkout(target_worktree, candidate.commit, request.mode)
            journal.unlink(missing_ok=True)
            try:
                state.write_history_checkpoint(repo, target, candidate.commit)
            except (OSError, InvariantError):
                # Checkpoints are disposable acceleration only; a landing that has
                # already advanced atomically must not be reported as failed.
                pass
        for unit in request.units:
            coordinate.release_lease(repo, unit, missing_ok=True)
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
        context = governance.context_result(verify_dir, base=base, history=history)
        reach_lines = context.lines
        if context.reach != Reach.LOCAL:
            raise Blocked(
                f"Invariant: direct edit has {context.reach.value} reach; use normal work-branch landing",
                lines=reach_lines,
            )
        scopes = context.topology
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
