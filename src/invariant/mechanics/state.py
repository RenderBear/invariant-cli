from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from invariant.mechanics import config, git, governance
from invariant.mechanics.documents import load_yaml
from invariant.mechanics.governance import architecture_refs, refs
from invariant.semantics.discovery import Discovery, validate_shape
from invariant.semantics.records import SemanticRecord, parse_document


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and git.valid_id(value)


def _markdown_anchor(path: Path, anchor: str) -> bool:
    if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
        return False
    from invariant.mechanics.governance import _heading_slug

    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match and _heading_slug(match.group(1)) == anchor:
            return True
    return False


def _authority(repo: Path, value: Any, label: str) -> list[str]:
    if not isinstance(value, str):
        return [f"{label} authority is not an inspectable user:, design:, or architecture: locator"]
    if value.startswith(("user:task:", "user:url:http://", "user:url:https://", "design:task:", "design:url:http://", "design:url:https://")):
        return []
    if value.startswith(("architecture:repo:", "design:repo:")):
        path = value.split(":repo:", 1)[1].split("#", 1)[0]
        return [] if (repo / path).exists() else [f"{label} authority target '{path}' does not exist"]
    return [f"{label} authority is not an inspectable user:, design:, or architecture: locator"]


def _architecture(repo: Path, value: str, label: str) -> list[str]:
    if not value.startswith("architecture:") or "#" not in value:
        return [f"{label} architecture '{value}' must use architecture:<markdown-path>#<decision-id>"]
    path_anchor = value.removeprefix("architecture:")
    path, anchor = path_anchor.split("#", 1)
    candidate = repo / path
    if candidate.suffix.lower() not in {".md", ".markdown"}:
        return [f"{label} architecture '{path}' must be Markdown"]
    if not candidate.is_file():
        return [f"{label} architecture '{path}' does not exist"]
    if not _markdown_anchor(candidate, anchor):
        return [f"{label} architecture anchor '#{anchor}' does not exist in {path}"]
    return []


def _material(repo: Path, value: str, label: str) -> list[str]:
    if value.startswith(("repo:", "architecture:", "adr:", "schema:")):
        path = value.split(":", 1)[1].split("#", 1)[0]
        return [] if (repo / path).exists() else [f"{label} material '{path}' does not exist"]
    if value.startswith(("task:", "url:http://", "url:https://")):
        return []
    return [f"{label} material '{value}' must use repo:, architecture:, adr:, schema:, task:, or url:"]


def _surface(repo: Path, value: str, label: str) -> list[str]:
    if value.startswith("repo:"):
        path = value.removeprefix("repo:").split("#", 1)[0]
        return [] if (repo / path).exists() else [f"{label} surface '{path}' does not exist"]
    if value.startswith("interface:") and value != "interface:":
        return []
    return [f"{label} surface '{value}' must use repo: or interface:"]


def _revisit_coordinate(value: str, label: str) -> list[str]:
    """Validate a future invalidation trigger; the named path may not exist yet."""

    if value.startswith("repo:"):
        path = value.removeprefix("repo:").split("#", 1)[0]
        relative = Path(path)
        if path and not relative.is_absolute() and ".." not in relative.parts:
            return []
    elif value.startswith("interface:") and value != "interface:":
        return []
    return [f"{label} revisit coordinate '{value}' must use a safe repo: or interface: locator"]


def _verifier(repo: Path, value: str, label: str) -> list[str]:
    def repository_path(path: str) -> tuple[Path, list[str]]:
        relative = Path(path)
        if not path or relative.is_absolute() or ".." in relative.parts:
            return repo / relative, [f"{label} verifier '{path}' must stay inside the repository"]
        candidate = repo / relative
        try:
            candidate.resolve().relative_to(repo.resolve())
        except (OSError, ValueError):
            return candidate, [f"{label} verifier '{path}' escapes the repository"]
        return candidate, []

    if value.startswith("command:"):
        path = value.removeprefix("command:")
        candidate, failures = repository_path(path)
        if failures:
            return failures
        result = [] if candidate.is_file() else [f"{label} verifier '{path}' does not exist"]
        if candidate.is_file() and not candidate.stat().st_mode & 0o111:
            result.append(f"{label} command verifier '{path}' is not executable")
        return result
    if value.startswith("test:"):
        path = value.removeprefix("test:").split("::", 1)[0]
        candidate, failures = repository_path(path)
        if failures:
            return failures
        return [] if candidate.is_file() else [f"{label} verifier '{path}' does not exist"]
    if value.startswith("schema:"):
        path = value.removeprefix("schema:").split("#", 1)[0]
        candidate, failures = repository_path(path)
        if failures:
            return failures
        return [] if candidate.is_file() else [f"{label} verifier '{path}' does not exist"]
    if value.startswith("runner:"):
        runner, separator, target = value.removeprefix("runner:").partition("#")
        if not separator or not git.valid_id(runner) or not target:
            return [f"{label} verifier '{value}' must use runner:<name>#<target>"]
        try:
            registered = config.resolve(repo).verification.named(runner)
        except InvariantError as exc:
            return [f"{label} verifier '{value}' cannot resolve configuration: {exc.message}"]
        return [] if registered else [f"{label} verifier runner '{runner}' is not registered"]
    return [f"{label} verifier '{value}' must use command:, test:, schema:, or runner:"]


def _evidence(repo: Path, value: str, label: str, at: str | None) -> list[str]:
    if value.startswith("repo:"):
        path = value.removeprefix("repo:").split("#", 1)[0]
        if at and at not in {"unborn", "empty"}:
            exists = git.run(["cat-file", "-e", f"{at}:{path}"], cwd=repo, check=False).returncode == 0
        else:
            exists = (repo / path).exists()
        return [] if exists else [f"{label} evidence '{path}' does not exist" + (f" at {at}" if at else "")]
    if value.startswith("commit:"):
        ref = value.removeprefix("commit:")
        return [] if git.resolve(repo, ref) else [f"{label} evidence commit '{ref}' does not resolve"]
    if value.startswith(("interface:", "task:", "url:http://", "url:https://")):
        return []
    return [f"{label} evidence '{value}' must use repo:, commit:, interface:, task:, or url:"]


def validate_audit(repo: Path, path: Path, raw: dict[str, Any], domain_ids: Iterable[str]) -> list[str]:
    """Validate one persisted audit record without requiring it to be written first."""
    failures: list[str] = []
    relative = path.relative_to(repo).as_posix() if repo in path.parents else path.as_posix()
    identifier = raw.get("id")
    if raw.get("version") != 1:
        failures.append(f"{relative} must declare version: 1")
    if not _valid_id(identifier):
        failures.append(f"{relative} invalid audit id '{identifier}'")
    if path.stem != identifier:
        failures.append(f"{relative} filename must be {identifier}.yml")
    created_at = raw.get("created_at")
    if not isinstance(created_at, str):
        failures.append(f"{relative} missing created_at timestamp")
    else:
        try:
            datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            failures.append(f"{relative} created_at must be a UTC RFC 3339 timestamp")
    if raw.get("mode") not in {"scope", "full"}:
        failures.append(f"{relative} invalid audit mode '{raw.get('mode')}'")
    if "findings" not in raw or not isinstance(raw.get("findings"), list):
        failures.append(f"{relative} missing findings")
    ground, tree = raw.get("ground"), raw.get("tree")
    if not ground:
        failures.append(f"{relative} missing ground")
    elif ground != "unborn" and not git.resolve(repo, str(ground)):
        failures.append(f"{relative} ground '{ground}' does not resolve")
    if not tree:
        failures.append(f"{relative} missing tree")
    elif tree != "empty" and git.resolve(repo, str(tree), "tree") is None:
        failures.append(f"{relative} tree '{tree}' does not resolve")
    known_domains = set(domain_ids)
    for domain in refs(raw.get("domains")):
        if domain not in known_domains:
            failures.append(f"{relative} references missing domain '{domain}'")
    paths = refs(raw.get("paths"))
    if raw.get("mode") == "scope" and not paths:
        failures.append(f"{relative} scoped audit requires at least one path")
    for audit_path in paths:
        if audit_path.startswith("/") or ".." in Path(audit_path).parts:
            failures.append(f"{relative} has invalid audit path '{audit_path}'")
        elif tree and tree != "empty" and git.run(
            ["cat-file", "-e", f"{tree}:{audit_path}"], cwd=repo, check=False
        ).returncode:
            failures.append(f"{relative} audit path '{audit_path}' does not exist in tree {tree}")
    finding_ids: list[str] = []
    for finding in raw.get("findings", []):
        if not isinstance(finding, dict):
            failures.append(f"{relative} finding must be a mapping")
            continue
        finding_unknown = sorted(
            set(finding) - {"id", "summary", "evidence", "proposed", "disposition", "authority"}
        )
        if finding_unknown:
            failures.append(f"{relative} finding has unknown field '{finding_unknown[0]}'")
        fid = finding.get("id")
        flabel = f"{relative}:{fid}"
        if not _valid_id(fid):
            failures.append(f"{relative} invalid finding id '{fid}'")
        else:
            finding_ids.append(str(fid))
        if not finding.get("summary"):
            failures.append(f"{flabel} missing summary")
        evidence = refs(finding.get("evidence"))
        if not evidence:
            failures.append(f"{flabel} requires evidence")
        for locator in evidence:
            failures.extend(_evidence(repo, locator, flabel, str(tree) if tree else None))
        if finding.get("proposed") not in {
            "domain", "contract", "architecture", "discovery", "none", "constraint", "observation"
        }:
            failures.append(f"{flabel} invalid proposed value '{finding.get('proposed')}'")
        if finding.get("disposition") not in {
            "adoptable", "needs-authority", "needs-verifier", "discovery-only", "no-action", "observation-only"
        }:
            failures.append(f"{flabel} invalid disposition '{finding.get('disposition')}'")
        if finding.get("authority"):
            failures.extend(_authority(repo, finding.get("authority"), flabel))
    if len(finding_ids) != len(set(finding_ids)):
        failures.append(f"{relative} finding ids must be unique")
    return failures


def _yaml_files(repo: Path, named: Iterable[str] = ()) -> list[Path]:
    output = git.run(
        ["ls-files", "--cached", "--others", "--exclude-standard", "--", ".invariant/"],
        cwd=repo,
        check=False,
    ).stdout
    values = {repo / item for item in output.splitlines() if item.endswith((".yml", ".yaml"))}
    values.update((repo / item if not Path(item).is_absolute() else Path(item)) for item in named)
    return sorted(values)


def _landing_history(repo: Path) -> list[str]:
    errors: list[str] = []
    commits = git.run(["rev-list", "--first-parent", "--reverse", "HEAD"], cwd=repo, check=False)
    if commits.returncode:
        return ["landing history HEAD does not resolve"]
    adopted = False
    last = ""
    gap = False
    gap_tip = ""
    for commit in commits.stdout.splitlines():
        boundary = git.trailers(repo, commit, "Invariant-Boundary")
        governance_refs = git.trailers(repo, commit, "Invariant-Governance")
        semantic_attestations = git.trailers(repo, commit, "Invariant-Semantic")
        covers = git.trailers(repo, commit, "Invariant-Covers")
        label = f"landing history commit {commit[:12]}"
        if not adopted and boundary:
            adopted = True
            if covers:
                errors.append(f"{label} has unexpected Invariant-Covers")
        if not adopted:
            continue
        if not boundary:
            gap = True
            gap_tip = commit
            continue
        if len(boundary) > 1:
            errors.append(f"{label} has multiple Invariant-Boundary trailers")
            continue
        value = boundary[0]
        if value not in {"no-record", "recorded"} and not re.fullmatch(r"audit:[A-Za-z0-9._-]+", value):
            errors.append(f"{label} has an invalid Invariant-Boundary disposition")
            continue
        if value == "recorded" and not governance_refs:
            errors.append(f"{label} uses Invariant-Boundary recorded without Invariant-Governance")
        semantic_refs = {
            reference.removeprefix("semantic:")
            for reference in governance_refs
            if reference.startswith("semantic:")
        }
        parsed_attestations: dict[str, str] = {}
        for attestation in semantic_attestations:
            identifier, separator, digest = attestation.partition("@")
            if (
                not separator
                or not git.valid_id(identifier)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                errors.append(f"{label} has invalid Invariant-Semantic attestation '{attestation}'")
                continue
            if identifier in parsed_attestations:
                errors.append(f"{label} attests semantic record '{identifier}' more than once")
            parsed_attestations[identifier] = digest
        for identifier in sorted(semantic_refs):
            if identifier not in parsed_attestations:
                errors.append(f"{label} does not bind semantic:{identifier} to canonical prose")
                continue
            try:
                expected_digest = governance.semantic_record_digest(repo, identifier, commit)
            except InvariantError as exc:
                errors.append(f"{label} {exc.message.removeprefix('Invariant: ')}")
                continue
            if parsed_attestations[identifier] != expected_digest:
                errors.append(f"{label} has stale semantic attestation for '{identifier}'")
        for identifier in sorted(set(parsed_attestations) - semantic_refs):
            errors.append(
                f"{label} attests semantic record '{identifier}' without Invariant-Governance"
            )
        if last:
            if gap:
                parent = git.resolve(repo, f"{commit}^1") or ""
                expected = f"{last}..{parent}"
                if not covers:
                    errors.append(f"{label} must cover unattested range {expected}")
                elif len(covers) > 1:
                    errors.append(f"{label} has multiple Invariant-Covers trailers")
                elif covers[0] != expected:
                    errors.append(f"{label} covers {covers[0]} but expected {expected}")
            elif covers:
                errors.append(f"{label} has Invariant-Covers without an unattested range")
        last = commit
        gap = False
    if adopted and gap:
        errors.append(f"unattested integration range {last}..{gap_tip} requires the next landing to carry Invariant-Covers")
    return errors


def validate(repo: Path, *, landing: bool = False, named: Iterable[str] = ()) -> list[str]:
    failures = _landing_history(repo) if landing else []
    files = _yaml_files(repo, named)
    if not files:
        if failures:
            return [*(f"FAIL {item}" for item in failures), f"{len(failures)} Invariant state violation(s)"]
        return ["no Invariant state — nothing to validate"]

    parsed: dict[Path, dict[str, Any]] = {}
    for path in files:
        relative = path.relative_to(repo).as_posix() if repo in path.parents else path.as_posix()
        if not path.is_file():
            failures.append(f"{relative} does not exist")
            continue
        try:
            raw = load_yaml(path)
        except Exception as exc:  # reported as state failure, not a traceback
            failures.append(f"{relative} {exc}")
            continue
        if not isinstance(raw, dict):
            failures.append(f"{relative} must contain a YAML mapping")
            continue
        parsed[path] = raw
        if raw.get("version") != 1:
            failures.append(f"{relative} must declare version: 1")

    domain_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []
    constraint_rows: list[dict[str, Any]] = []
    discovery_rows: list[tuple[Path, Discovery, dict[str, Any]]] = []
    audit_rows: list[tuple[Path, dict[str, Any]]] = []
    observation_rows: list[tuple[Path, dict[str, Any]]] = []
    semantic_rows: list[SemanticRecord] = []

    for path, raw in parsed.items():
        relative = path.relative_to(repo).as_posix() if repo in path.parents else path.as_posix()
        if relative == ".invariant/config.yml":
            try:
                config.resolve(repo)
            except Exception as exc:
                failures.append(f"{relative} {str(exc).removeprefix('Invariant: ')}")
        elif relative == ".invariant/SEMANTICS.yml":
            try:
                semantic_rows.extend(parse_document(raw))
            except InvariantError as exc:
                failures.append(f"{relative} {exc.message.removeprefix('Invariant: ')}")
        elif relative == ".invariant/DOMAINS.yml":
            values = raw.get("domains")
            if not isinstance(values, list) or not values:
                failures.append(f"{relative} contains no domains; remove it")
            else:
                domain_rows.extend(item for item in values if isinstance(item, dict))
        elif relative == ".invariant/CONTRACTS.yml":
            values = raw.get("contracts")
            if not isinstance(values, list) or not values:
                failures.append(f"{relative} contains no contracts; remove it")
            else:
                contract_rows.extend(item for item in values if isinstance(item, dict))
        elif relative == ".invariant/CONSTRAINTS.yml":
            values = raw.get("constraints")
            if not isinstance(values, list) or not values:
                failures.append(f"{relative} contains no constraints; remove it")
            else:
                constraint_rows.extend(item for item in values if isinstance(item, dict))
        elif relative.startswith(".invariant/audits/"):
            audit_rows.append((path, raw))
        elif relative.startswith(".invariant/discoveries/"):
            failures.extend(validate_shape(Path(relative), raw))
            discovery_rows.append((path, Discovery.parse(raw), raw))
        elif relative.startswith(".invariant/observations/"):
            observation_rows.append((path, raw))
        else:
            failures.append(
                f"{relative} is not a version-1 config, semantic record, domain, contract, legacy constraint, audit, discovery, or observation file"
            )

    domain_ids = [str(row.get("id", "")) for row in domain_rows]
    contract_ids = [str(row.get("id", "")) for row in contract_rows]
    constraint_ids = [str(row.get("id", "")) for row in constraint_rows]
    discovery_ids = [row.identifier for _, row, _ in discovery_rows]
    semantic_ids = [row.identifier for row in semantic_rows]
    for name, values in (("domain", domain_ids), ("contract", contract_ids), ("constraint", constraint_ids), ("discovery", discovery_ids)):
        for value in sorted({item for item in values if values.count(item) > 1}):
            failures.append(f"duplicate {name} '{value}'")

    semantic_by_id = {row.identifier: row for row in semantic_rows}
    for row in semantic_rows:
        label = f".invariant/SEMANTICS.yml:{row.identifier}"
        failures.extend(_authority(repo, row.authority, label))
        failures.extend(_architecture(repo, row.document, label))
        if not row.applies_to and not row.revisit_on:
            failures.append(f"{label} requires applies_to or revisit_on coordinates")
        for locator in row.applies_to:
            if locator.startswith("domain:"):
                domain = locator.removeprefix("domain:")
                if domain not in domain_ids:
                    failures.append(f"{label} references missing domain '{domain}'")
            elif locator.startswith(("repo:", "interface:")):
                failures.extend(_surface(repo, locator, label))
            else:
                failures.append(
                    f"{label} applicability '{locator}' must use repo:, interface:, or domain:"
                )
        for locator in row.revisit_on:
            if locator.startswith("semantic:"):
                target = locator.removeprefix("semantic:")
                if target not in semantic_ids:
                    failures.append(f"{label} revisits missing semantic record '{target}'")
            elif locator.startswith(("repo:", "interface:")):
                failures.extend(_revisit_coordinate(locator, label))
            else:
                failures.append(
                    f"{label} revisit coordinate '{locator}' must use repo:, interface:, or semantic:"
                )
        for locator in row.verifies:
            failures.extend(_verifier(repo, locator, label))
        for target in row.supersedes:
            if target == row.identifier:
                failures.append(f"{label} cannot supersede itself")
            elif target not in semantic_by_id:
                failures.append(f"{label} supersedes missing semantic record '{target}'")
            elif semantic_by_id[target].status != "superseded":
                failures.append(
                    f"{label} supersedes '{target}', but that record is not marked superseded"
                )
        for relation, targets in row.relations.items():
            for target in targets:
                semantic = target.removeprefix("semantic:")
                if target.startswith("semantic:") and semantic not in semantic_by_id:
                    failures.append(
                        f"{label} relation '{relation}' references missing semantic record '{semantic}'"
                    )

    parents: dict[str, str] = {}
    for row in domain_rows:
        identifier = row.get("id")
        label = f".invariant/DOMAINS.yml:{identifier}"
        if not _valid_id(identifier):
            failures.append(f".invariant/DOMAINS.yml invalid domain id '{identifier}'")
        if not row.get("responsibility") and not row.get("description"):
            failures.append(f"{label} missing responsibility")
        failures.extend(_authority(repo, row.get("authority"), label))
        parent = row.get("parent")
        if parent:
            if parent not in domain_ids:
                failures.append(f"{label} references missing parent '{parent}'")
            else:
                parents[str(identifier)] = str(parent)
        if row.get("architecture") and row.get("material"):
            failures.append(f"{label} use architecture, not both architecture and legacy material")
        for locator in architecture_refs(row.get("architecture")):
            failures.extend(_architecture(repo, locator, label))
        for locator in refs(row.get("material")):
            failures.extend(_material(repo, locator, label))
        for contract in refs(row.get("contracts")):
            if contract not in contract_ids:
                failures.append(f"{label} references missing contract '{contract}'")
    for identifier in parents:
        seen: set[str] = set()
        current = identifier
        while current in parents:
            if current in seen:
                failures.append("domain parent graph contains a cycle")
                break
            seen.add(current)
            current = parents[current]

    for row in contract_rows:
        identifier = row.get("id")
        label = f".invariant/CONTRACTS.yml:{identifier}"
        if not _valid_id(identifier):
            failures.append(f".invariant/CONTRACTS.yml invalid contract id '{identifier}'")
        if not row.get("assertion"):
            failures.append(f"{label} missing assertion")
        failures.extend(_authority(repo, row.get("authority"), label))
        between = refs(row.get("between"))
        if len(between) < 2:
            failures.append(f"{label} requires at least two domains in between")
        for domain in between:
            if domain not in domain_ids:
                failures.append(f"{label} references missing domain '{domain}'")
        surfaces = refs(row.get("surfaces"))
        if not surfaces:
            failures.append(f"{label} requires at least one surface")
        for locator in surfaces:
            failures.extend(_surface(repo, locator, label))
        defining = architecture_refs(row.get("architecture"))
        for locator in defining:
            failures.extend(_architecture(repo, locator, label))
        for locator in refs(row.get("material")):
            failures.extend(_material(repo, locator, label))
        if not defining and not refs(row.get("material")):
            failures.append(f"{label} requires defining material")
        verifiers = refs(row.get("verifies"))
        if not verifiers:
            failures.append(f"{label} requires executable verification")
        for locator in verifiers:
            failures.extend(_verifier(repo, locator, label))

    for row in constraint_rows:
        identifier = row.get("id")
        label = f".invariant/CONSTRAINTS.yml:{identifier}"
        if not _valid_id(identifier):
            failures.append(f".invariant/CONSTRAINTS.yml invalid constraint id '{identifier}'")
        if not row.get("assertion"):
            failures.append(f"{label} missing assertion")
        failures.extend(_authority(repo, row.get("authority"), label))
        applies = refs(row.get("applies_to"))
        if not applies:
            failures.append(f"{label} requires at least one domain in applies_to")
        for domain in applies:
            if domain not in domain_ids:
                failures.append(f"{label} references missing domain '{domain}'")
        for locator in refs(row.get("surfaces")):
            failures.extend(_surface(repo, locator, label))
        materials = refs(row.get("material"))
        if not materials:
            failures.append(f"{label} requires defining material")
        for locator in materials:
            failures.extend(_material(repo, locator, label))
        for locator in refs(row.get("verifies")):
            failures.extend(_verifier(repo, locator, label))

    for path, raw in audit_rows:
        failures.extend(validate_audit(repo, path, raw, domain_ids))

    for path, discovery, raw in discovery_rows:
        relative = path.relative_to(repo).as_posix()
        if discovery.basis.ground and discovery.basis.ground != "unborn" and not git.resolve(repo, discovery.basis.ground):
            failures.append(f"{relative} ground '{discovery.basis.ground}' does not resolve")
        if discovery.basis.tree and discovery.basis.tree != "empty" and git.resolve(repo, discovery.basis.tree, "tree") is None:
            failures.append(f"{relative} tree '{discovery.basis.tree}' does not resolve")
        for domain in discovery.domains:
            if domain not in domain_ids:
                failures.append(f"{relative} references missing domain '{domain}'")
        for locator in discovery.basis.evidence:
            failures.extend(_evidence(repo, locator, f"{relative}:{discovery.identifier}", discovery.basis.tree))
        for related in discovery.related:
            if related.startswith("domain:") and related.removeprefix("domain:") not in domain_ids:
                failures.append(f"{relative}:{discovery.identifier} relates to missing '{related}'")
            elif related.startswith("contract:") and related.removeprefix("contract:") not in contract_ids:
                failures.append(f"{relative}:{discovery.identifier} relates to missing '{related}'")
        for output in discovery.disposition.outputs:
            if output.startswith("domain:") and output.removeprefix("domain:") not in domain_ids:
                failures.append(f"{relative}:{discovery.identifier} resolves to missing '{output}'")
            elif output.startswith("contract:") and output.removeprefix("contract:") not in contract_ids:
                failures.append(f"{relative}:{discovery.identifier} resolves to missing '{output}'")
            elif output.startswith("architecture:"):
                failures.extend(_architecture(repo, output, f"{relative}:{discovery.identifier}"))
            elif output.startswith("discovery:") and output.removeprefix("discovery:") not in discovery_ids:
                failures.append(f"{relative}:{discovery.identifier} resolves to missing '{output}'")
            elif output.startswith("path:"):
                if not (repo / output.removeprefix("path:")).exists():
                    failures.append(f"{relative}:{discovery.identifier} output path is missing '{output}'")
            elif not output.startswith("task:"):
                failures.append(
                    f"{relative}:{discovery.identifier} output '{output}' must name domain:, contract:, architecture:, discovery:, path:, or task:"
                )

    for path, raw in observation_rows:
        relative = path.relative_to(repo).as_posix()
        identifier = raw.get("id")
        label = f"{relative}:{identifier}"
        if not _valid_id(identifier):
            failures.append(f"{relative} invalid observation id '{identifier}'")
        if path.stem != identifier:
            failures.append(f"{relative} filename must be {identifier}.yml")
        if not raw.get("statement"):
            failures.append(f"{label} missing statement")
        ground = raw.get("ground")
        if not ground:
            failures.append(f"{label} missing ground")
        for locator in refs(raw.get("evidence")):
            failures.extend(_evidence(repo, locator, label, str(ground) if ground else None))

    if failures:
        return [*(f"FAIL {item}" for item in failures), f"{len(failures)} Invariant state violation(s)"]
    return ["Invariant state valid"]
