from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import git, governance, state
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.semantics.discovery import Discovery


def snapshot(repo: Path, *, exclude: list[str] | None = None) -> tuple[str, str]:
    ground = git.resolve(repo, "HEAD") or "unborn"
    descriptor, index_name = tempfile.mkstemp(prefix="invariant-audit-index.")
    os.close(descriptor)
    Path(index_name).unlink()
    environment = {"GIT_INDEX_FILE": index_name}
    try:
        if ground == "unborn":
            git.run(["read-tree", "--empty"], cwd=repo, env=environment)
        else:
            git.run(["read-tree", f"{ground}^{{tree}}"], cwd=repo, env=environment)
        git.run(["add", "-A", "--", "."], cwd=repo, env=environment, check=False)
        for path in exclude or []:
            if ground == "unborn":
                git.run(
                    ["update-index", "--force-remove", "--", path],
                    cwd=repo,
                    env=environment,
                    check=False,
                )
            else:
                git.run(["reset", "-q", ground, "--", path], cwd=repo, env=environment)
        tree = git.run(["write-tree"], cwd=repo, env=environment).stdout
    finally:
        Path(index_name).unlink(missing_ok=True)
    return ground, tree


def _records(repo: Path) -> list[str]:
    output: list[str] = []
    for label, rows in (
        ("DOMAIN", governance.domains(repo)),
        ("CONTRACT", governance.contracts(repo)),
        ("LEGACY-CONSTRAINT", governance.constraints(repo)),
    ):
        output.extend(f"{label}: {row.get('id')}" for row in rows if row.get("id"))
    directory = repo / ".invariant" / "discoveries"
    if directory.is_dir():
        for path in sorted(directory.glob("*.yml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(raw, dict):
                discovery = Discovery.parse(raw)
                status = discovery.legacy_status or discovery.disposition.state
                output.append(f"DISCOVERY: {discovery.identifier} ({status})")
    return output


def _sources(repo: Path) -> list[str]:
    paths = git.run(["ls-files"], cwd=repo, check=False).stdout.splitlines()
    output: list[str] = []
    for path in paths:
        low = path.lower()
        name = Path(low).name
        parts = Path(low).parts
        if (
            any(part in {"architecture", "adr", "adrs"} for part in parts)
            or name in {"readme.md", "architecture.md", "architecture.markdown"}
            or name.startswith(("openapi", "asyncapi"))
            or "schema" in name
            or Path(low).suffix in {".drawio", ".mmd", ".mermaid"}
        ):
            output.append(f"SOURCE: {path}")
        if (
            name in {"makefile", "justfile", "taskfile.yml", "taskfile.yaml", "package.json", "pyproject.toml", "cargo.toml", "go.mod"}
            or low.startswith(".github/workflows/")
        ):
            output.append(f"CHECK-SOURCE: {path}")
    return output


def frame(repo: Path, mode: str, paths: list[str] | None = None) -> list[str]:
    ground, tree = snapshot(repo)
    output = [f"AUDIT: {mode}", f"GROUND: {ground}", f"TREE: {tree}"]
    if mode == "scope":
        for path in paths or []:
            output.append(f"PATH: {path}")
            output.extend(
                line.replace("TOPOLOGY:", "DERIVED:", 1)
                for line in governance.reach(repo, paths=[path])
                if line.startswith("TOPOLOGY:")
            )
    else:
        output.extend(governance.context_map(repo))
    output.extend(_records(repo))
    output.extend(_sources(repo))
    output.append("STATE-VALIDATION:")
    output.extend(state.validate(repo))
    output.append(
        "NEXT: investigate and classify findings, then save the completed audit with "
        "'invariant evidence audit save'"
    )
    return output


def full(repo: Path, authority: str) -> list[str]:
    return [f"AUTHORITY: {authority}", *frame(repo, "full")]


def save(
    repo: Path,
    identifier: str,
    *,
    mode: str,
    source: Path,
    paths: list[str],
    domains: list[str],
    authority: str,
) -> list[str]:
    if not git.valid_id(identifier):
        raise InvariantError(f"Invariant: invalid audit id '{identifier}'", code="invalid_audit")
    if mode == "scope" and not paths:
        raise InvariantError(
            "Invariant: a scoped audit requires at least one --path", code="invalid_audit"
        )
    if mode == "full" and paths:
        raise InvariantError("Invariant: a full audit does not accept --path", code="invalid_audit")
    raw = load_yaml(source)
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 1
        or not isinstance(raw.get("findings"), list)
    ):
        raise InvariantError(
            "Invariant: audit input must be a version-1 mapping with a findings list",
            code="invalid_audit",
        )
    unknown = sorted(set(raw) - {"version", "findings"})
    if unknown:
        raise InvariantError(
            f"Invariant: audit input has unknown field '{unknown[0]}'; ground, tree, id, and "
            "mode are stamped by Invariant",
            code="invalid_audit",
        )
    excluded: list[str] = []
    try:
        excluded.append(source.resolve().relative_to(repo.resolve()).as_posix())
    except ValueError:
        pass
    ground, tree = snapshot(repo, exclude=excluded)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    stamped_identifier = f"{identifier}-{timestamp}"
    suffix = 2
    destination = repo / ".invariant" / "audits" / f"{stamped_identifier}.yml"
    while destination.exists():
        stamped_identifier = f"{identifier}-{timestamp}-{suffix}"
        destination = repo / ".invariant" / "audits" / f"{stamped_identifier}.yml"
        suffix += 1
    value: dict[str, Any] = {
        "version": 1,
        "id": stamped_identifier,
        "created_at": created_at,
        "ground": ground,
        "tree": tree,
        "mode": mode,
    }
    if paths:
        value["paths"] = sorted(set(paths))
    if domains:
        value["domains"] = sorted(set(domains))
    value["findings"] = raw["findings"]
    domain_ids = [str(row.get("id")) for row in governance.domains(repo) if row.get("id")]
    failures = state.validate_audit(repo, destination, value, domain_ids)
    if failures:
        raise InvariantError(
            f"Invariant: invalid audit: {failures[0]}",
            code="invalid_audit",
            lines=[f"INVALID: {failure}" for failure in failures],
        )
    dump_yaml(destination, value)
    if authority == "agent":
        next_step = (
            "NEXT: adopt every ready finding through the managed task lifecycle; preserve unresolved "
            "contradictions as evidence and escalate only decisions outside agent authority"
        )
    else:
        next_step = (
            "NEXT: give the human a concise findings summary with choices to investigate further, "
            "adopt all ready findings, adopt selected findings, or defer adoption"
        )
    return [
        f"AUDIT: {stamped_identifier}",
        f"CREATED-AT: {created_at}",
        f"AUTHORITY: {authority}",
        f"GROUND: {ground}",
        f"TREE: {tree}",
        f"SAVED: {destination.relative_to(repo)}",
        next_step,
    ]


def _load_evidence(repo: Path, locator: str) -> tuple[Path, dict[str, Any], str]:
    value = Path(locator)
    candidates: list[Path]
    if "/" in locator:
        candidates = [value if value.is_absolute() else repo / value]
    else:
        candidates = [
            repo / ".invariant" / "audits" / f"{locator}.yml",
            repo / ".invariant" / "discoveries" / f"{locator}.yml",
        ]
    for path in candidates:
        if path.is_file():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise InvariantError(f"Invariant: invalid YAML in {path}: {exc}") from exc
            if isinstance(raw, dict):
                kind = "discovery" if "/discoveries/" in path.as_posix() else "audit"
                return path, raw, kind
    raise InvariantError(f"Invariant: no audit or discovery '{locator}'", code="missing_evidence")


def fresh(repo: Path, locator: str, head: str = "HEAD") -> list[str]:
    path, raw, kind = _load_evidence(repo, locator)
    if kind == "discovery":
        discovery = Discovery.parse(raw)
        ground = discovery.basis.ground
        tree = discovery.basis.tree
        mode = "scope"
        watched = [*discovery.basis.evidence, *(f"repo:{item}" for item in discovery.basis.searched), *(f"repo:{item}" for item in discovery.paths)]
        domains = discovery.domains
    else:
        ground = str(raw.get("ground") or "")
        tree = str(raw.get("tree") or "")
        mode = str(raw.get("mode") or "")
        watched = [f"repo:{item}" for item in governance.refs(raw.get("paths"))]
        for finding in raw.get("findings", []):
            if isinstance(finding, dict):
                watched.extend(governance.refs(finding.get("evidence")))
        domains = governance.refs(raw.get("domains"))
    if not ground:
        raise InvariantError(f"Invariant: {kind} has no ground")
    if not tree:
        raise InvariantError(f"Invariant: {kind} has no tree")
    if ground == "unborn":
        if git.resolve(repo, head):
            raise Blocked(f"STALE: {kind} predates the root commit", code="stale_evidence")
        return ["FRESH: repository remains unborn"]
    resolved_head = git.resolve(repo, head)
    if not resolved_head:
        raise InvariantError(f"Invariant: head '{head}' does not resolve")
    if git.resolve(repo, tree, "tree") is None:
        raise InvariantError(f"Invariant: {kind} tree '{tree}' does not resolve")
    if not git.is_ancestor(repo, ground, resolved_head):
        raise Blocked(f"DIVERGED: {ground} is not an ancestor of {head}", code="diverged_evidence")
    relative = path.relative_to(repo).as_posix()
    changed = [item for item in git.changed_paths(repo, tree, f"{resolved_head}^{{tree}}") if item != relative]
    if not changed:
        return ["FRESH: head matches the audited tree"]
    if mode == "full":
        raise Blocked(f"STALE: repository-wide audited tree differs at {changed[0]}", code="stale_evidence")
    for evidence in watched:
        if not evidence.startswith("repo:"):
            continue
        watched_path = evidence.removeprefix("repo:").split("#", 1)[0]
        for candidate in changed:
            if governance.paths_related(candidate, watched_path):
                raise Blocked(f"STALE: changed evidence {candidate}", code="stale_evidence")
    if domains and any(path in governance.GOVERNANCE_FILES for path in changed):
        raise Blocked("STALE: selected-domain governance changed since the audited tree", code="stale_evidence")
    return ["FRESH: head differs only outside the recorded scope and evidence"]


def capture_discovery(
    repo: Path,
    identifier: str,
    *,
    observation: str,
    evidence: list[str],
    searched: list[str],
    domains: list[str],
    paths: list[str],
    related: list[str],
    basis_prose: str = "",
    dry_run: bool = False,
) -> list[str]:
    if not git.valid_id(identifier):
        raise InvariantError(f"Invariant: invalid discovery id '{identifier}'")
    if not observation.strip():
        raise InvariantError("Invariant: discovery requires observation prose")
    if not evidence and not searched:
        raise InvariantError("Invariant: discovery requires evidence or an explicit searched scope")
    ground, tree = snapshot(repo)
    value: dict[str, Any] = {
        "version": 1,
        "id": identifier,
        "observation": observation,
        "basis": {
            "ground": ground,
            "tree": tree,
        },
    }
    if evidence:
        value["basis"]["evidence"] = sorted(set(evidence))
    if searched:
        value["basis"]["searched"] = sorted(set(searched))
    if basis_prose:
        value["basis"]["prose"] = basis_prose
    relevance: dict[str, Any] = {}
    if domains:
        relevance["domains"] = sorted(set(domains))
    if paths:
        relevance["paths"] = sorted(set(paths))
    if related:
        relevance["related"] = sorted(set(related))
    if relevance:
        value["relevance"] = relevance
    value["disposition"] = {"state": "open"}
    destination = repo / ".invariant" / "discoveries" / f"{identifier}.yml"
    if destination.exists():
        raise InvariantError(f"Invariant: discovery '{identifier}' already exists")
    if not dry_run:
        dump_yaml(destination, value)
    action = "WOULD-RECORD" if dry_run else "RECORDED"
    return [
        f"DISCOVERY: {identifier}",
        f"STATUS: {'proposed' if dry_run else 'open'}",
        f"GROUND: {ground}",
        f"TREE: {tree}",
        f"{action}: {destination.relative_to(repo)}",
    ]


def resolve_discovery(
    repo: Path,
    identifier: str,
    *,
    prose: str,
    outputs: list[str],
    dry_run: bool = False,
) -> list[str]:
    path = repo / ".invariant" / "discoveries" / f"{identifier}.yml"
    if not path.is_file():
        raise InvariantError(f"Invariant: no discovery '{identifier}'")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise InvariantError(f"Invariant: invalid discovery '{identifier}'")
    discovery = Discovery.parse(raw)
    if discovery.disposition.state != "open":
        raise InvariantError(f"Invariant: discovery '{identifier}' is already resolved")
    if not prose.strip() and not outputs:
        raise InvariantError("Invariant: discovery resolution requires prose or outputs")
    raw.pop("status", None)
    raw.pop("resolution", None)
    raw.pop("reason", None)
    disposition: dict[str, Any] = {"state": "resolved"}
    if prose:
        disposition["prose"] = prose
    if outputs:
        disposition["outputs"] = sorted(set(outputs))
    raw["disposition"] = disposition
    if not dry_run:
        dump_yaml(path, raw)
    action = "WOULD-RESOLVE" if dry_run else "RESOLVED"
    return [
        f"DISCOVERY: {identifier}",
        f"STATUS: {'proposed' if dry_run else 'resolved'}",
        f"{action}: {path.relative_to(repo)}",
    ]
