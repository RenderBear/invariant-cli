from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from invariant.errors import Blocked, InvariantError


@dataclass(frozen=True)
class CompletedGit:
    stdout: str
    stderr: str
    returncode: int


def run(
    args: Iterable[str],
    *,
    cwd: Path | str | None = None,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CompletedGit:
    command = ["git", *args]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=process_env,
        check=False,
    )
    result = CompletedGit(completed.stdout.rstrip("\n"), completed.stderr.rstrip("\n"), completed.returncode)
    if check and result.returncode:
        detail = result.stderr or result.stdout or "Git command failed"
        raise InvariantError(f"Invariant: {detail}", code="git_failed")
    return result


def require_capabilities(repo: Path) -> None:
    """Fail before mutation when Git lacks mechanics required by Invariant."""
    version = run(["--version"], cwd=repo, check=False)
    merge_tree_help = run(["merge-tree", "-h"], cwd=repo, check=False)
    worktrees = run(["worktree", "list", "--porcelain"], cwd=repo, check=False)
    commit_tree_help = run(["commit-tree", "-h"], cwd=repo, check=False)
    update_ref_help = run(["update-ref", "-h"], cwd=repo, check=False)
    symbolic_ref_help = run(["symbolic-ref", "-h"], cwd=repo, check=False)
    missing: list[str] = []
    if "--write-tree" not in f"{merge_tree_help.stdout}\n{merge_tree_help.stderr}":
        missing.append("git merge-tree --write-tree")
    if worktrees.returncode:
        missing.append("git worktree porcelain support")
    if "commit-tree" not in f"{commit_tree_help.stdout}\n{commit_tree_help.stderr}":
        missing.append("git commit-tree")
    update_help = f"{update_ref_help.stdout}\n{update_ref_help.stderr}"
    if "update-ref" not in update_help or "old" not in update_help:
        missing.append("git update-ref compare-and-swap")
    if "symbolic-ref" not in f"{symbolic_ref_help.stdout}\n{symbolic_ref_help.stderr}":
        missing.append("git symbolic-ref")
    if missing:
        label = version.stdout or version.stderr or "unknown Git version"
        raise InvariantError(
            "Invariant: installed Git lacks required exact-candidate capabilities",
            code="unsupported_git",
            lines=[
                f"GIT: {label}",
                *[f"MISSING: {capability}" for capability in missing],
                "NEXT: install a Git release that provides the missing capabilities, then retry",
            ],
        )


def root(cwd: Path | str | None = None) -> Path:
    result = run(["rev-parse", "--show-toplevel"], cwd=cwd, check=False)
    if result.returncode:
        raise InvariantError("Invariant: not inside a Git repository", code="not_repository")
    return Path(result.stdout).resolve()


def tracked_nested_invariant_paths(repo: Path) -> list[str]:
    """Return tracked Invariant state below the one repository root.

    A separate nested Git repository is not part of the parent's tracked file
    set, so this detects only competing kernels inside the same atomic Git
    boundary.
    """

    result = run(
        ["ls-files", "--cached", "--", ":(glob)**/.invariant/**"],
        cwd=repo,
        check=False,
    )
    return sorted(
        path
        for path in result.stdout.splitlines()
        if path and path.split("/").index(".invariant") > 0
    )


def common_dir(repo: Path) -> Path:
    value = run(["rev-parse", "--git-common-dir"], cwd=repo).stdout
    path = Path(value)
    return (path if path.is_absolute() else repo / path).resolve()


def current_branch(repo: Path) -> str | None:
    result = run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo, check=False)
    return result.stdout or None


def resolve(repo: Path, ref: str, kind: str = "commit") -> str | None:
    suffix = f"^{{{kind}}}" if kind else ""
    result = run(["rev-parse", "-q", "--verify", f"{ref}{suffix}"], cwd=repo, check=False)
    return (result.stdout or None) if result.returncode == 0 else None


def branch_exists(repo: Path, branch: str) -> bool:
    return run(["show-ref", "--verify", "-q", f"refs/heads/{branch}"], cwd=repo, check=False).returncode == 0


def is_ancestor(repo: Path, base: str, tip: str) -> bool:
    return run(["merge-base", "--is-ancestor", base, tip], cwd=repo, check=False).returncode == 0


def is_first_parent_ancestor(repo: Path, base: str, tip: str) -> bool:
    if base == tip:
        return True
    history = run(
        ["rev-list", "--first-parent", "--reverse", f"{base}..{tip}"],
        cwd=repo,
        check=False,
    )
    commits = history.stdout.splitlines() if history.returncode == 0 else []
    return bool(commits) and resolve(repo, f"{commits[0]}^1") == base


def hash_text(repo: Path, value: str) -> str:
    return run(["hash-object", "--stdin"], cwd=repo, input_text=value).stdout


def tree_text_files(repo: Path, ref: str, prefix: str) -> dict[str, str]:
    """Read every text file below one tree prefix with a single Git process."""

    completed = subprocess.run(
        ["git", "archive", "--format=tar", ref, prefix],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode(errors="replace")
        if "did not match any files" in detail:
            return {}
        raise InvariantError(
            f"Invariant: {detail.strip() or 'Git archive failed'}", code="git_failed"
        )
    output: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is not None:
                output[member.name] = source.read().decode("utf-8")
    return output


def changed_paths(repo: Path, base: str | None = None, tip: str | None = None) -> list[str]:
    if tip is not None:
        result = run(["diff", "--name-only", base or "HEAD", tip, "--"], cwd=repo)
        return sorted(set(result.stdout.splitlines())) if result.stdout else []
    if base:
        result = run(["diff", "--name-only", base, "HEAD", "--"], cwd=repo)
        return sorted(set(result.stdout.splitlines())) if result.stdout else []
    values: list[str] = []
    for args in (
        ["diff", "--name-only", "HEAD", "--"],
        ["diff", "--name-only", "--cached", "--"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        result = run(args, cwd=repo, check=False)
        values.extend(result.stdout.splitlines())
    return sorted(set(filter(None, values)))


def history_changed_paths(repo: Path, base: str, tip: str = "HEAD") -> list[str]:
    result = run(
        [
            "log",
            "--first-parent",
            "--diff-merges=first-parent",
            "--format=",
            "--name-only",
            "-z",
            f"{base}..{tip}",
            "--",
        ],
        cwd=repo,
    )
    return sorted({path for path in result.stdout.split("\0") if path})


def worktree_for_branch(repo: Path, branch: str) -> Path | None:
    output = run(["worktree", "list", "--porcelain"], cwd=repo).stdout.splitlines()
    path: Path | None = None
    for line in output:
        if line.startswith("worktree "):
            path = Path(line[9:])
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    return None


def primary_worktree(repo: Path) -> Path:
    output = run(["worktree", "list", "--porcelain"], cwd=repo).stdout.splitlines()
    for line in output:
        if line.startswith("worktree "):
            return Path(line[9:]).resolve()
    return repo


def worktree_clean(repo: Path, *, include_untracked: bool = True) -> bool:
    args = ["status", "--porcelain"]
    if include_untracked:
        args.append("--untracked-files=normal")
    return not run(args, cwd=repo).stdout


def tracked_worktree_clean(repo: Path) -> bool:
    return (
        run(["diff", "--quiet", "--"], cwd=repo, check=False).returncode == 0
        and run(["diff", "--cached", "--quiet", "--"], cwd=repo, check=False).returncode == 0
    )


def merge_tree(repo: Path, base: str, tip: str) -> str:
    result = run(["merge-tree", "--write-tree", base, tip], cwd=repo, check=False)
    # merge-tree exits 1 only for content conflicts; any other status is a Git failure.
    if result.returncode == 1:
        lines = [line for line in (result.stdout, result.stderr) if line]
        raise Blocked(
            "Invariant: prospective merge conflicts; integration branch unchanged",
            code="merge_conflict",
            lines=lines,
        )
    if result.returncode:
        detail = result.stderr or result.stdout or "Git command failed"
        raise InvariantError(f"Invariant: {detail}", code="git_failed")
    return result.stdout.splitlines()[0]


def trailers(repo: Path, commit: str, key: str) -> list[str]:
    separator = "%x1d"
    result = run(
        ["log", "-1", f"--format=%(trailers:key={key},valueonly,separator={separator})", commit],
        cwd=repo,
        check=False,
    )
    if result.returncode or not result.stdout:
        return []
    return [item for item in result.stdout.replace("\x1d", "\n").splitlines() if item]


@dataclass(frozen=True)
class TrailerCommit:
    commit: str
    parents: tuple[str, ...]
    trailers: Mapping[str, tuple[str, ...]]


def trailer_history(
    repo: Path, tip: str, keys: Iterable[str], *, after: str | None = None
) -> list[TrailerCommit] | None:
    """Return first-parent commits reaching `tip`, oldest first, with the requested trailers.

    One Git invocation formats the whole range. `after` excludes that commit and its
    ancestors so callers can skip history that predates the trailers they inspect.
    """

    key_values = list(keys)
    fields = "".join(
        f"%x00%(trailers:key={key},valueonly,separator=%x1d)" for key in key_values
    )
    arguments = ["log", "--first-parent", "--reverse", f"--format=%H%x00%P{fields}%x1e", tip]
    if after:
        arguments.append(f"^{after}")
    result = run(arguments, cwd=repo, check=False)
    if result.returncode:
        return None
    history: list[TrailerCommit] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00")
        if len(parts) != len(key_values) + 2:
            continue
        values = {
            key: tuple(item for item in parts[index + 2].split("\x1d") if item)
            for index, key in enumerate(key_values)
        }
        history.append(TrailerCommit(parts[0], tuple(parts[1].split()), values))
    return history


def commits_mentioning(
    repo: Path, tip: str, key: str, *, after: str | None = None
) -> list[str]:
    """Return first-parent commits reaching `tip`, newest first, whose message names a trailer key."""

    arguments = ["rev-list", "--first-parent", f"--grep=^{key}:", tip]
    if after:
        arguments.append(f"^{after}")
    result = run(arguments, cwd=repo, check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


def valid_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value))


def object_format(repo: Path) -> str:
    result = run(["rev-parse", "--show-object-format"], cwd=repo, check=False)
    return result.stdout if result.returncode == 0 and result.stdout else "sha1"


def zero_oid(repo: Path) -> str:
    return "0" * (64 if object_format(repo) == "sha256" else 40)


def tree_of(repo: Path, commit: str) -> str:
    value = resolve(repo, commit, "tree")
    if not value:
        raise InvariantError(f"Invariant: missing Git object '{commit}'", code="missing_object")
    return value


def write_blob(repo: Path, content: str) -> str:
    return run(["hash-object", "-w", "--stdin"], cwd=repo, input_text=content).stdout


def write_tree(repo: Path, files: Mapping[str, str]) -> str:
    """Write a flat tree whose values are already-created blob ids."""

    rows = "".join(f"100644 blob {oid}\t{name}\n" for name, oid in sorted(files.items()))
    return run(["mktree"], cwd=repo, input_text=rows).stdout


def commit_tree(
    repo: Path,
    tree: str,
    message: str,
    *,
    parents: Iterable[str] = (),
    timestamp: int | None = None,
) -> str:
    args = ["commit-tree", tree]
    for parent in parents:
        args.extend(["-p", parent])
    env = {
        "GIT_AUTHOR_NAME": "Invariant",
        "GIT_AUTHOR_EMAIL": "invariant@localhost",
        "GIT_COMMITTER_NAME": "Invariant",
        "GIT_COMMITTER_EMAIL": "invariant@localhost",
    }
    if timestamp is not None:
        date = f"{timestamp} +0000"
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return run(args, cwd=repo, input_text=message, env=env).stdout


def update_ref(repo: Path, ref: str, new: str, old: str | None) -> bool:
    expected = old or zero_oid(repo)
    return run(["update-ref", ref, new, expected], cwd=repo, check=False).returncode == 0


def delete_ref(repo: Path, ref: str, old: str) -> bool:
    return run(["update-ref", "-d", ref, old], cwd=repo, check=False).returncode == 0


def cat_files(repo: Path, specifications: Iterable[str]) -> dict[str, bytes]:
    """Read many ``commit:path`` blobs through one Git process."""

    values = list(specifications)
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        input="".join(f"{value}\n" for value in values).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise InvariantError(
            f"Invariant: {completed.stderr.decode(errors='replace').strip()}",
            code="git_failed",
        )
    stream = io.BytesIO(completed.stdout)
    result: dict[str, bytes] = {}
    for specification in values:
        header = stream.readline().decode("utf-8", errors="replace").rstrip("\n")
        if header.endswith(" missing"):
            raise InvariantError(
                f"Invariant: missing Git object '{specification}'", code="missing_object"
            )
        parts = header.split()
        if len(parts) != 3 or parts[1] != "blob":
            raise InvariantError(
                f"Invariant: '{specification}' is not a blob", code="corrupt_ledger"
            )
        size = int(parts[2])
        result[specification] = stream.read(size)
        if stream.read(1) != b"\n":
            raise InvariantError("Invariant: malformed Git batch output", code="git_failed")
    return result
