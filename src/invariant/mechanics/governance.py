from __future__ import annotations

import re
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

import yaml

from invariant.errors import InvariantError
from invariant.mechanics import git
from invariant.semantics.records import SemanticRecord, parse_document


GOVERNANCE_FILES = (
    ".invariant/SEMANTICS.yml",
    ".invariant/DOMAINS.yml",
    ".invariant/CONTRACTS.yml",
    ".invariant/CONSTRAINTS.yml",
)
TEST_DIRECTORIES = {"tests", "test", "spec", "__tests__"}
PACKAGE_MARKERS = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}


def refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        stripped = value.strip().strip("[]")
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return []


def _load(repo: Path, relative: str, at: str | None = None) -> dict[str, Any]:
    if at:
        result = git.run(["show", f"{at}:{relative}"], cwd=repo, check=False)
        if result.returncode or not result.stdout:
            return {}
        try:
            raw = yaml.safe_load(result.stdout)
        except yaml.YAMLError as exc:
            raise InvariantError(f"Invariant: invalid YAML in {relative} at {at}: {exc}") from exc
    else:
        path = repo / relative
        if not path.is_file():
            return {}
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise InvariantError(f"Invariant: invalid YAML in {relative}: {exc}") from exc
    return raw if isinstance(raw, dict) else {}


def domains(repo: Path, at: str | None = None) -> list[dict[str, Any]]:
    value = _load(repo, ".invariant/DOMAINS.yml", at).get("domains", [])
    return value if isinstance(value, list) else []


def contracts(repo: Path, at: str | None = None) -> list[dict[str, Any]]:
    value = _load(repo, ".invariant/CONTRACTS.yml", at).get("contracts", [])
    return value if isinstance(value, list) else []


def constraints(repo: Path, at: str | None = None) -> list[dict[str, Any]]:
    value = _load(repo, ".invariant/CONSTRAINTS.yml", at).get("constraints", [])
    return value if isinstance(value, list) else []


def semantic_records(repo: Path, at: str | None = None) -> list[SemanticRecord]:
    raw = _load(repo, ".invariant/SEMANTICS.yml", at)
    if not raw:
        return []
    return parse_document(raw)


def semantic_record_digest(repo: Path, identifier: str, at: str | None = None) -> str:
    """Digest the indexed envelope and its exact canonical Markdown section."""

    record = next(
        (item for item in semantic_records(repo, at) if item.identifier == identifier),
        None,
    )
    if record is None:
        raise InvariantError(f"Invariant: unknown semantic record '{identifier}'")
    document = record.document.removeprefix("architecture:")
    path, _, anchor = document.partition("#")
    content = _content(repo, at, path)
    bounds = _section_bounds(content, anchor) if anchor else None
    body = (
        "\n".join(content.splitlines()[bounds[0] - 1 : bounds[1]])
        if bounds
        else content
    )
    payload = {
        "id": record.identifier,
        "document": record.document,
        "authority": record.authority,
        "status": record.status,
        "applies_to": record.applies_to,
        "revisit_on": record.revisit_on,
        "verifies": record.verifies,
        "supersedes": record.supersedes,
        "relations": record.relations,
        "facets": record.facets,
        "body": body,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def applicable_semantic_records(
    repo: Path,
    *,
    paths: Iterable[str] = (),
    selected_domains: Iterable[str] = (),
    interfaces: Iterable[str] = (),
    at: str | None = None,
) -> list[SemanticRecord]:
    """Select records by their small retrieval envelope, without interpreting prose."""

    changed = list(paths)
    domains_selected = set(expand_domains(repo, selected_domains, at))
    interfaces_selected = set(interfaces)

    def path_related(locator: str) -> bool:
        path, _ = _locator_path(locator)
        return bool(path and any(paths_related(candidate, path) for candidate in changed))

    active = [record for record in semantic_records(repo, at) if record.status == "active"]
    selected: dict[str, SemanticRecord] = {}
    for record in active:
        coordinates = [record.document, *record.applies_to, *record.revisit_on]
        if (
            any(
                locator.startswith("domain:")
                and locator.removeprefix("domain:") in domains_selected
                for locator in record.applies_to
            )
            or any(
                locator.startswith("interface:")
                and locator.removeprefix("interface:") in interfaces_selected
                for locator in [*record.applies_to, *record.revisit_on]
            )
            or any(path_related(locator) for locator in coordinates)
        ):
            selected[record.identifier] = record

    # A record that explicitly revisits when another selected interpretation
    # changes belongs in the same retrieval context. Relations remain open and
    # descriptive; only revisit_on has this mechanical meaning.
    expanded_context = True
    while expanded_context:
        expanded_context = False
        selected_ids = set(selected)
        for record in active:
            dependencies = {
                locator.removeprefix("semantic:")
                for locator in record.revisit_on
                if locator.startswith("semantic:")
            }
            if record.identifier not in selected and dependencies.intersection(selected_ids):
                selected[record.identifier] = record
                expanded_context = True
    return sorted(selected.values(), key=lambda item: item.identifier)


def expand_domains(repo: Path, selected: Iterable[str], at: str | None = None) -> list[str]:
    rows = {str(row.get("id")): row for row in domains(repo, at) if row.get("id")}
    expanded = set(selected)
    pending = list(expanded)
    while pending:
        item = pending.pop()
        if item not in rows:
            raise InvariantError(f"Invariant: unknown semantic domain '{item}'", exit_code=1, code="unknown_domain")
        parent = rows[item].get("parent")
        if isinstance(parent, str) and parent and parent not in expanded:
            expanded.add(parent)
            pending.append(parent)
    return sorted(expanded)


def architecture_refs(value: Any) -> list[str]:
    return [item for item in refs(value) if item.startswith("architecture:")]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", value.lower())


def derived_scopes(repo: Path, path: str) -> list[str]:
    if path == ".invariant" or path.startswith(".invariant/"):
        return []
    parts = Path(path).parts
    if len(parts) <= 1 or parts[0].startswith("."):
        return ["area.root"]
    result = [f"area.{slug(parts[0])}"]
    directory = repo / Path(*parts[:-1])
    while directory != repo and repo in directory.parents:
        for marker in PACKAGE_MARKERS:
            if (directory / marker).is_file():
                result.append(f"pkg.{slug(directory.name)}")
                break
        directory = directory.parent
    return sorted(set(result))


def scopes_for_tree(repo: Path, ref: str) -> list[str]:
    output = git.run(["ls-tree", "-r", "--name-only", ref, "--"], cwd=repo, check=False).stdout
    result: set[str] = set()
    for path in output.splitlines():
        if path == ".invariant" or path.startswith(".invariant/"):
            continue
        parts = Path(path).parts
        if len(parts) == 1 or parts[0].startswith("."):
            result.add("area.root")
        else:
            result.add(f"area.{slug(parts[0])}")
        if parts and parts[-1] in PACKAGE_MARKERS and len(parts) > 1:
            result.add(f"pkg.{slug(parts[-2])}")
    return sorted(result)


def context_map(repo: Path) -> list[str]:
    output = git.run(["ls-files", "--"], cwd=repo, check=False).stdout
    directories: set[str] = set()
    root_seen = False
    for path in output.splitlines():
        parts = Path(path).parts
        if not parts or parts[0] == ".invariant":
            continue
        if len(parts) == 1 or parts[0].startswith("."):
            root_seen = True
        else:
            directories.add(parts[0])
    lines: list[str] = []
    for directory in sorted(directories):
        if directory in TEST_DIRECTORIES:
            lines.append(f"ATTACH: {directory} — canonical test paths attach to code boundaries")
        else:
            lines.append(f"BOUNDARY: area.{slug(directory)} {directory}")
    if root_seen:
        lines.append("BOUNDARY: area.root .")
    return lines


def _locator_path(locator: str) -> tuple[str | None, str | None]:
    if locator.startswith(("task:", "url:", "interface:", "commit:")):
        return None, None
    value = locator.split(":", 1)[1] if ":" in locator else locator
    value = value.split("::", 1)[0]
    if "#" in value:
        path, anchor = value.split("#", 1)
        return path, anchor
    return value, None


def paths_related(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def _heading_slug(value: str) -> str:
    value = re.sub(r"[`*_~]", "", value.lower())
    value = re.sub(r"[^a-z0-9 _-]", "", value)
    value = re.sub(r"\s+", "-", value).strip("-")
    return value


def _section_bounds(content: str, anchor: str) -> tuple[int, int] | None:
    headings: list[tuple[int, int, str]] = []
    lines = content.splitlines()
    for number, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.append((number, len(match.group(1)), _heading_slug(match.group(2))))
    for index, (start, level, found) in enumerate(headings):
        if found != anchor:
            continue
        end = len(lines)
        for next_start, next_level, _ in headings[index + 1 :]:
            if next_level <= level:
                end = next_start - 1
                break
        return start, end
    return None


def _content(repo: Path, ref: str | None, path: str) -> str:
    if ref:
        return git.run(["show", f"{ref}:{path}"], cwd=repo, check=False).stdout
    candidate = repo / path
    return candidate.read_text(encoding="utf-8") if candidate.is_file() else ""


def _changed_ranges(diff: str) -> list[tuple[int, int, int, int]]:
    ranges: list[tuple[int, int, int, int]] = []
    for line in diff.splitlines():
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            ranges.append(
                (
                    int(match.group(1)),
                    int(match.group(2) or "1"),
                    int(match.group(3)),
                    int(match.group(4) or "1"),
                )
            )
    return ranges


def markdown_section_hit(repo: Path, path: str, anchor: str, base: str | None, tip: str | None = None) -> bool | None:
    if Path(path).suffix.lower() not in {".md", ".markdown"}:
        return None
    comparison = base or "HEAD"
    args = ["diff", "--unified=0", comparison]
    if tip:
        args.append(tip)
    args.extend(["--", path])
    diff = git.run(args, cwd=repo, check=False).stdout
    ranges = _changed_ranges(diff)
    if not ranges:
        return None
    old = _content(repo, comparison, path)
    new = _content(repo, tip, path) if tip else _content(repo, None, path)
    old_bounds = _section_bounds(old, anchor)
    new_bounds = _section_bounds(new, anchor)
    if not old_bounds and not new_bounds:
        return None

    def overlaps(start: int, count: int, bounds: tuple[int, int] | None) -> bool:
        if not bounds or count <= 0:
            return False
        return start <= bounds[1] and start + count - 1 >= bounds[0]

    return any(overlaps(os, oc, old_bounds) or overlaps(ns, nc, new_bounds) for os, oc, ns, nc in ranges)


def path_hits(
    repo: Path,
    changed: Iterable[str],
    locators: Any,
    base: str | None = None,
    tip: str | None = None,
) -> bool:
    changed_values = list(changed)
    for locator in refs(locators):
        path, anchor = _locator_path(locator)
        if not path:
            continue
        for candidate in changed_values:
            if not paths_related(candidate, path):
                continue
            if candidate == path and anchor:
                section = markdown_section_hit(repo, path, anchor, base, tip)
                if section is False:
                    continue
            return True
    return False


def first_path_intersection(changed: Iterable[str], locators: Any) -> str | None:
    for locator in refs(locators):
        if not locator.startswith(("repo:", "architecture:", "adr:", "schema:")):
            continue
        path, _ = _locator_path(locator)
        if path:
            for candidate in changed:
                if paths_related(candidate, path):
                    return candidate
    return None


@dataclass(frozen=True)
class Affected:
    kind: str
    identifier: str
    level: str
    verifies: tuple[str, ...]
    assertion: str


def _domain_contract_ids(repo: Path, selected: set[str], at: str | None = None) -> set[str]:
    result: set[str] = set()
    for row in domains(repo, at):
        if row.get("id") in selected:
            result.update(refs(row.get("contracts")))
    return result


def compile_affected(
    repo: Path,
    paths: Iterable[str],
    selected_domains: Iterable[str],
    interfaces: Iterable[str],
    *,
    base: str | None = None,
    tip: str | None = None,
    at: str | None = None,
) -> list[Affected]:
    changed = list(paths)
    selected = set(expand_domains(repo, selected_domains, at))
    interface_set = set(interfaces)
    selected_contracts = _domain_contract_ids(repo, selected, at)
    base_contracts = (
        {str(row.get("id")): row for row in contracts(repo, base) if row.get("id")}
        if base
        else {}
    )
    base_domains = (
        {str(row.get("id")): row for row in domains(repo, base) if row.get("id")}
        if base
        else {}
    )
    base_constraints = (
        {str(row.get("id")): row for row in constraints(repo, base) if row.get("id")}
        if base
        else {}
    )
    base_semantics = (
        {row.identifier: row for row in semantic_records(repo, base)} if base else {}
    )
    affected: dict[tuple[str, str], Affected] = {}

    def add(item: Affected) -> None:
        key = (item.kind, item.identifier)
        existing = affected.get(key)
        if existing is None or item.level == "open":
            affected[key] = item

    semantic_rows = semantic_records(repo, at)
    changed_semantic_meaning: set[str] = set()
    for record in semantic_rows:
        if (
            ".invariant/SEMANTICS.yml" in changed
            and base_semantics.get(record.identifier) != record
        ) or path_hits(
            repo,
            changed,
            [record.document, *record.revisit_on, *record.verifies],
            base,
            tip,
        ):
            changed_semantic_meaning.add(record.identifier)

    semantic_levels: dict[str, str] = {}
    for record in semantic_rows:
        if record.status != "active":
            continue
        applies = record.applies_to
        applies_domains = {
            item.removeprefix("domain:")
            for item in applies
            if item.startswith("domain:")
        }
        level = ""
        if record.identifier in changed_semantic_meaning:
            level = "open"
        if not level and (
            selected.intersection(applies_domains)
            or path_hits(repo, changed, applies, base, tip)
            or any(
                item == f"interface:{name}"
                for name in interface_set
                for item in applies
            )
        ):
            level = "bounded"
        if level:
            semantic_levels[record.identifier] = level

    # Revisit dependencies propagate only semantic change events. Merely
    # touching code within B's applicability may retrieve A for context, but
    # does not claim that B's interpretation—and therefore A—changed.
    propagated = True
    while propagated:
        propagated = False
        for record in semantic_rows:
            if record.status != "active":
                continue
            dependencies = {
                locator.removeprefix("semantic:")
                for locator in record.revisit_on
                if locator.startswith("semantic:")
            }
            if dependencies.intersection(changed_semantic_meaning):
                if semantic_levels.get(record.identifier) != "open":
                    semantic_levels[record.identifier] = "open"
                    propagated = True
                if record.identifier not in changed_semantic_meaning:
                    changed_semantic_meaning.add(record.identifier)
                    propagated = True

    for record in semantic_rows:
        level = semantic_levels.get(record.identifier, "")
        if level:
            add(
                Affected(
                    "semantic",
                    record.identifier,
                    level,
                    tuple(record.verifies),
                    f"Review {record.document} as canonical prose.",
                )
            )
            if record.document.startswith("architecture:"):
                add(
                    Affected(
                        "architecture",
                        record.document.removeprefix("architecture:"),
                        level,
                        (),
                        "Review the referenced semantic record.",
                    )
                )

    for row in contracts(repo, at):
        identifier = str(row.get("id", ""))
        between = set(refs(row.get("between")))
        surfaces = refs(row.get("surfaces"))
        architecture = row.get("architecture", row.get("material"))
        verifies = tuple(refs(row.get("verifies")))
        level = ""
        if ".invariant/CONTRACTS.yml" in changed and base_contracts.get(identifier) != row:
            level = "open"
        if not level and (
            selected.intersection(between)
            or identifier in selected_contracts
            or path_hits(repo, changed, surfaces, base, tip)
            or any(surface == f"interface:{name}" for name in interface_set for surface in surfaces)
        ):
            level = "bounded"
        if path_hits(repo, changed, architecture, base, tip) or path_hits(repo, changed, verifies, base, tip):
            level = "open"
        if level:
            add(Affected("contract", identifier, level, verifies, str(row.get("assertion", ""))))
            for locator in architecture_refs(architecture):
                architecture_level = "open" if path_hits(repo, changed, [locator], base, tip) else level
                add(
                    Affected(
                        "architecture",
                        locator.removeprefix("architecture:"),
                        architecture_level,
                        (),
                        "Review the referenced architectural decision.",
                    )
                )

    for row in domains(repo, at):
        identifier = str(row.get("id", ""))
        for locator in architecture_refs(row.get("architecture", row.get("material"))):
            level = "bounded" if identifier in selected else ""
            if ".invariant/DOMAINS.yml" in changed and base_domains.get(identifier) != row:
                level = "open"
            if path_hits(repo, changed, [locator], base, tip):
                level = "open"
            if level:
                add(
                    Affected(
                        "architecture",
                        locator.removeprefix("architecture:"),
                        level,
                        (),
                        "Review the referenced architectural decision.",
                    )
                )

    for row in constraints(repo, at):
        applies = set(refs(row.get("applies_to")))
        surfaces = refs(row.get("surfaces"))
        material = row.get("material")
        verifies = tuple(refs(row.get("verifies")))
        level = ""
        identifier = str(row.get("id", ""))
        if ".invariant/CONSTRAINTS.yml" in changed and base_constraints.get(identifier) != row:
            level = "open"
        if not level and (
            selected.intersection(applies)
            or path_hits(repo, changed, surfaces, base, tip)
            or any(surface == f"interface:{name}" for name in interface_set for surface in surfaces)
        ):
            level = "bounded"
        if path_hits(repo, changed, material, base, tip) or path_hits(repo, changed, verifies, base, tip):
            level = "open"
        if level:
            add(
                Affected(
                    "constraint",
                    identifier,
                    level,
                    verifies,
                    str(row.get("assertion", "")),
                )
            )
    return sorted(affected.values(), key=lambda item: (item.kind, item.identifier))


def _governance_change_class(repo: Path, paths: list[str], base: str | None, tip: str | None = None) -> str:
    if not any(path in GOVERNANCE_FILES for path in paths):
        return "none"
    if not base:
        existing_change = False
        for relative in GOVERNANCE_FILES:
            tracked = git.run(["ls-files", "--error-unmatch", relative], cwd=repo, check=False).returncode == 0
            if tracked and git.run(["diff", "--quiet", "HEAD", "--", relative], cwd=repo, check=False).returncode:
                existing_change = True
        return "gated" if existing_change else "open"
    args = ["diff", "--unified=0", base]
    if tip:
        args.append(tip)
    args.extend(["--", *GOVERNANCE_FILES])
    diff = git.run(args, cwd=repo, check=False).stdout
    removed = any(line.startswith("-") and not line.startswith("---") for line in diff.splitlines())
    return "gated" if removed else "open"


def _discovery_records(repo: Path) -> list[tuple[Path, dict[str, Any]]]:
    directory = repo / ".invariant" / "discoveries"
    result: list[tuple[Path, dict[str, Any]]] = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.yml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(raw, dict):
            result.append((path, raw))
    return result


def _relevant_discoveries(
    repo: Path, paths: list[str], selected_domains: list[str]
) -> list[tuple[dict[str, Any], str, str | None]]:
    output: list[tuple[dict[str, Any], str, str | None]] = []
    selected = set(selected_domains)
    head = git.resolve(repo, "HEAD")
    for _, row in _discovery_records(repo):
        disposition = row.get("disposition") if isinstance(row.get("disposition"), dict) else {}
        status = str(row.get("status") or disposition.get("state") or "open")
        if status not in {"pending", "stale", "open"}:
            continue
        relevance = row.get("relevance") if isinstance(row.get("relevance"), dict) else {}
        basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
        selected_refs = refs(row.get("domains")) + refs(relevance.get("domains"))
        evidence = refs(row.get("evidence")) + refs(basis.get("evidence")) + [
            f"repo:{item}" for item in refs(basis.get("paths")) + refs(relevance.get("paths"))
        ]
        if not selected.intersection(selected_refs) and not path_hits(repo, paths, evidence):
            continue
        state = status
        detail: str | None = None
        ground = str(row.get("ground") or basis.get("ground") or "")
        tree = str(row.get("tree") or basis.get("tree") or "")
        if status in {"pending", "open"}:
            if ground and ground != "unborn" and (not head or not git.is_ancestor(repo, ground, head)):
                state = "diverged"
            elif tree and tree != "empty" and head:
                changed = git.changed_paths(repo, tree, f"{head}^{{tree}}")
                if path_hits(repo, changed, evidence):
                    state = "needs-review"
                    detail = first_path_intersection(changed, evidence)
        identifier = row.get("id")
        if identifier:
            output.append((row, state, detail))
    return output


def discovery_lines(repo: Path, paths: list[str], selected_domains: list[str]) -> list[str]:
    output: list[str] = []
    for row, state, detail in _relevant_discoveries(repo, paths, selected_domains):
        identifier = row.get("id")
        if detail:
            output.append(f"DISCOVERY: {identifier} ({state} — changed evidence {detail})")
        else:
            output.append(f"DISCOVERY: {identifier} ({state})")
    return output


def discovery_context(repo: Path, paths: list[str], selected_domains: list[str]) -> list[str]:
    """Compile relevant discovery prose without granting it governing standing."""

    output: list[str] = []
    for row, state, detail in _relevant_discoveries(repo, paths, selected_domains):
        basis = row.get("basis") if isinstance(row.get("basis"), dict) else {}
        relevance = row.get("relevance") if isinstance(row.get("relevance"), dict) else {}
        identifier = row.get("id")
        suffix = f" — changed evidence {detail}" if detail else ""
        output.append(f"DISCOVERY-CONTEXT: {identifier} ({state}{suffix})")

        def prose(label: str, value: Any) -> None:
            if not isinstance(value, str) or not value.strip():
                return
            output.append(f"{label}:")
            output.extend(f"  {line}" for line in value.strip().splitlines())

        prose("OBSERVATION", row.get("observation") or row.get("statement"))
        prose("BASIS", basis.get("prose"))
        evidence = refs(basis.get("evidence")) + refs(row.get("evidence"))
        searched = refs(basis.get("searched"))
        relevant_domains = refs(relevance.get("domains")) + refs(row.get("domains"))
        relevant_paths = refs(relevance.get("paths")) + refs(row.get("paths"))
        related = refs(relevance.get("related"))
        if evidence:
            output.append(f"EVIDENCE: {', '.join(sorted(set(evidence)))}")
        if searched:
            output.append(f"SEARCHED: {', '.join(sorted(set(searched)))}")
        if relevant_domains:
            output.append(f"DISCOVERY-DOMAINS: {', '.join(sorted(set(relevant_domains)))}")
        if relevant_paths:
            output.append(f"DISCOVERY-PATHS: {', '.join(sorted(set(relevant_paths)))}")
        if related:
            output.append(f"RELATED: {', '.join(sorted(set(related)))}")
    return output


def reach(
    repo: Path,
    *,
    paths: list[str] | None = None,
    domains_selected: list[str] | None = None,
    interfaces: list[str] | None = None,
    base: str | None = None,
    history: bool = False,
    root_mode: bool = False,
) -> list[str]:
    selected = domains_selected or []
    interface_values = interfaces or []
    if paths is None:
        if root_mode:
            output = git.run(["ls-tree", "-r", "--name-only", "HEAD", "--"], cwd=repo, check=False).stdout
            changed = output.splitlines()
        elif history and base:
            changed = git.history_changed_paths(repo, base)
        else:
            changed = git.changed_paths(repo, base)
    else:
        changed = sorted(set(paths))
    expanded = expand_domains(repo, selected)
    affected = compile_affected(repo, changed, expanded, interface_values, base=base)
    scopes = sorted({scope for path in changed for scope in derived_scopes(repo, path)})
    lines = [f"TOPOLOGY: {scope}" for scope in scopes]
    comparison = base or git.resolve(repo, "HEAD")
    if comparison:
        base_scopes = set(scopes_for_tree(repo, comparison))
        for scope in scopes:
            if scope in {"area.tests", "area.test", "area.spec", "area.__tests__"}:
                continue
            if scope not in base_scopes:
                lines.append(f"TOPOLOGY-NEW: {scope}")
    for item in affected:
        lines.append(f"AFFECTED: {item.kind}:{item.identifier} ({item.level})")
        if item.kind in {"architecture", "constraint"}:
            lines.append(f"REVIEW: {item.kind}:{item.identifier} {item.assertion}")
    lines.extend(discovery_lines(repo, changed, expanded))
    structural = _governance_change_class(repo, changed, base)
    if structural == "gated":
        lines.append("GOVERNANCE: existing accepted record changed or removed")
        verdict = "gated"
    elif structural == "open":
        lines.append("GOVERNANCE: additive record establishment")
        verdict = "open"
    elif any(item.level == "open" for item in affected):
        verdict = "open"
    elif affected:
        verdict = "bounded"
    else:
        verdict = "local"
    lines.append(f"REACH: {verdict}")
    return lines


def verifiers(
    repo: Path,
    *,
    paths: list[str] | None = None,
    domains_selected: list[str] | None = None,
    interfaces: list[str] | None = None,
    base: str | None = None,
    history: bool = False,
    root_mode: bool = False,
) -> list[str]:
    if paths is None:
        if root_mode:
            changed = git.run(["ls-tree", "-r", "--name-only", "HEAD", "--"], cwd=repo).stdout.splitlines()
        elif history and base:
            changed = git.history_changed_paths(repo, base)
        else:
            changed = git.changed_paths(repo, base)
    else:
        changed = paths
    affected = compile_affected(repo, changed, domains_selected or [], interfaces or [], base=base)
    lines: list[str] = []
    for item in affected:
        if item.kind in {"architecture", "constraint"}:
            lines.append(f"REVIEW: {item.kind}:{item.identifier} {item.assertion}")
        for locator in item.verifies:
            lines.append(f"VERIFY: {item.kind}:{item.identifier} {locator}")
    return lines


def governing_rows(repo: Path, selected: Iterable[str], at: str | None = None) -> list[str]:
    expanded = set(expand_domains(repo, selected, at))
    selected_contracts = _domain_contract_ids(repo, expanded, at)
    rows: list[str] = []
    for record in semantic_records(repo, at):
        applies_domains = {
            item.removeprefix("domain:")
            for item in record.applies_to
            if item.startswith("domain:")
        }
        if applies_domains and not expanded.intersection(applies_domains):
            continue
        if not applies_domains and expanded:
            continue
        rows.append(_semantic_row(repo, record, at))
    for row in domains(repo, at):
        if row.get("id") not in expanded:
            continue
        rows.append(
            "DOMAIN|{id}|{parent}|{responsibility}|{architecture}|{contracts}|{authority}".format(
                id=row.get("id", ""),
                parent=row.get("parent", ""),
                responsibility=row.get("responsibility", row.get("description", "")),
                architecture=" ".join(refs(row.get("architecture", row.get("material")))),
                contracts=" ".join(refs(row.get("contracts"))),
                authority=row.get("authority", ""),
            )
        )
    for row in contracts(repo, at):
        if not expanded.intersection(refs(row.get("between"))) and row.get("id") not in selected_contracts:
            continue
        rows.append(
            "CONTRACT|{id}|{between}|{surfaces}|{architecture}|{verifies}|{assertion}|{authority}".format(
                id=row.get("id", ""),
                between=" ".join(refs(row.get("between"))),
                surfaces=" ".join(refs(row.get("surfaces"))),
                architecture=" ".join(refs(row.get("architecture", row.get("material")))),
                verifies=" ".join(refs(row.get("verifies"))),
                assertion=str(row.get("assertion", "")).replace("|", "%7C"),
                authority=row.get("authority", ""),
            )
        )
    for row in constraints(repo, at):
        if expanded.intersection(refs(row.get("applies_to"))):
            rows.append(
                "CONSTRAINT|{id}|{applies}|{surfaces}|{material}|{verifies}|{assertion}|{authority}".format(
                    id=row.get("id", ""),
                    applies=" ".join(refs(row.get("applies_to"))),
                    surfaces=" ".join(refs(row.get("surfaces"))),
                    material=" ".join(refs(row.get("material"))),
                    verifies=" ".join(refs(row.get("verifies"))),
                    assertion=str(row.get("assertion", "")).replace("|", "%7C"),
                    authority=row.get("authority", ""),
                )
            )
    return sorted(rows)


def _semantic_row(repo: Path, record: SemanticRecord, at: str | None = None) -> str:
    return "SEMANTIC|{id}|{status}|{document}|{applies}|{revisit}|{verifies}|{authority}|{digest}".format(
        id=record.identifier,
        status=record.status,
        document=record.document,
        applies=" ".join(record.applies_to),
        revisit=" ".join(record.revisit_on),
        verifies=" ".join(record.verifies),
        authority=record.authority,
        digest=semantic_record_digest(repo, record.identifier, at),
    )


def display_rows(repo: Path, selected: Iterable[str], at: str | None = None) -> list[str]:
    output: set[str] = set()
    for row in governing_rows(repo, selected, at):
        values = row.split("|")
        if values[0] == "SEMANTIC":
            output.add(
                f"SEMANTIC {values[1]} ({values[2]}) — {values[3]}"
            )
            if values[3].startswith("architecture:"):
                output.add(f"ARCHITECTURE {values[3]}")
        elif values[0] == "DOMAIN":
            output.add(f"DOMAIN {values[1]} — {values[3]}")
            for locator in architecture_refs(values[4]):
                output.add(f"ARCHITECTURE {locator}")
        elif values[0] == "CONTRACT":
            output.add(f"CONTRACT {values[1]} — {values[6]}")
            for locator in architecture_refs(values[4]):
                output.add(f"ARCHITECTURE {locator}")
        elif values[0] == "CONSTRAINT":
            output.add(f"LEGACY-CONSTRAINT {values[1]} — {values[6]}")
    lines = sorted(output)
    return [*lines, f"ROWS: {len(lines)}"]


def architecture_context(
    repo: Path,
    selected: Iterable[str],
    at: str | None = None,
    *,
    paths: Iterable[str] = (),
    interfaces: Iterable[str] = (),
) -> list[str]:
    """Return canonical selected architecture sections, not only their pointers."""

    selected_values = list(selected)
    expanded = set(expand_domains(repo, selected_values, at))
    selected_contracts = _domain_contract_ids(repo, expanded, at)
    locators: set[str] = set()
    for record in applicable_semantic_records(
        repo,
        paths=paths,
        selected_domains=expanded,
        interfaces=interfaces,
        at=at,
    ):
        if record.document.startswith("architecture:"):
            locators.add(record.document)
    for row in domains(repo, at):
        if row.get("id") in expanded:
            locators.update(architecture_refs(row.get("architecture", row.get("material"))))
    for row in contracts(repo, at):
        if expanded.intersection(refs(row.get("between"))) or row.get("id") in selected_contracts:
            locators.update(architecture_refs(row.get("architecture", row.get("material"))))
    for row in constraints(repo, at):
        if expanded.intersection(refs(row.get("applies_to"))):
            locators.update(architecture_refs(row.get("material")))
    output: list[str] = []
    for locator in sorted(locators):
        path_anchor = locator.removeprefix("architecture:")
        if "#" not in path_anchor:
            continue
        path, anchor = path_anchor.split("#", 1)
        content = _content(repo, at, path)
        bounds = _section_bounds(content, anchor)
        output.append(f"ARCHITECTURE-CONTEXT: {locator}")
        if not bounds:
            output.append("  [selected section is unavailable]")
            continue
        lines = content.splitlines()[bounds[0] - 1 : bounds[1]]
        output.extend(f"  {line}" if line else "" for line in lines)
    return output


def digest(repo: Path, selected: Iterable[str], at: str | None = None) -> str:
    if at and not git.resolve(repo, at):
        raise InvariantError(f"Invariant: governance commit '{at}' does not resolve")
    content = "\n".join(governing_rows(repo, selected, at))
    if content:
        content += "\n"
    return git.hash_text(repo, content)


def context_digest(
    repo: Path,
    selected: Iterable[str],
    paths: Iterable[str],
    interfaces: Iterable[str],
    at: str | None = None,
) -> str:
    """Digest only governance retrievable from one task's semantic coordinates."""

    if at and not git.resolve(repo, at):
        raise InvariantError(f"Invariant: governance commit '{at}' does not resolve")
    legacy = [row for row in governing_rows(repo, selected, at) if not row.startswith("SEMANTIC|")]
    semantic = [
        _semantic_row(repo, record, at)
        for record in applicable_semantic_records(
            repo,
            paths=paths,
            selected_domains=selected,
            interfaces=interfaces,
            at=at,
        )
    ]
    content = "\n".join(sorted([*legacy, *semantic]))
    return git.hash_text(repo, content + ("\n" if content else ""))


def material_changes(repo: Path, base: str, tip: str, selected: Iterable[str]) -> list[str]:
    if not git.resolve(repo, base):
        raise InvariantError(f"Invariant: material base '{base}' does not resolve")
    if not git.resolve(repo, tip):
        raise InvariantError(f"Invariant: material tip '{tip}' does not resolve")
    changed = git.changed_paths(repo, base, tip)
    output: set[str] = set()
    for row in governing_rows(repo, selected, tip):
        values = row.split("|")
        if values[0] not in {"DOMAIN", "CONTRACT", "CONSTRAINT"}:
            continue
        for locator in refs(values[4]):
            if not locator.startswith(("task:", "url:")) and path_hits(repo, changed, [locator], base, tip):
                output.add(f"MATERIAL-CHANGED: {locator}")
    return sorted(output)


def commit_message(
    repo: Path,
    subject: str,
    units: Iterable[str],
    scopes: Iterable[str],
    selected_domains: Iterable[str] = (),
    plan: str | None = None,
) -> str:
    unit_values = list(units)
    scope_values = list(scopes)
    if not unit_values or not scope_values:
        raise InvariantError("Invariant: commit message requires units and scopes")
    lines = [subject, ""]
    lines.extend(f"Invariant-Unit: {item}" for item in unit_values)
    lines.extend(f"Invariant-Scope: {item}" for item in scope_values)
    lines.extend(f"Invariant-Domain: {item}" for item in selected_domains)
    if plan:
        plan_file = git.primary_worktree(repo) / ".invariant" / "runtime" / "plans" / f"{plan}.yml"
        if not plan_file.is_file():
            raise InvariantError(f"Invariant: no plan '{plan}' to stamp")
        import zlib

        data = plan_file.read_bytes()
        lines.append(f"Invariant-Plan: {plan}")
        lines.append(f"Invariant-Plan-Digest: {zlib.crc32(data) & 0xffffffff}-{len(data)}")
    return "\n".join(lines) + "\n"


def validate_trailer(repo: Path, commit: str) -> list[str]:
    claimed = git.trailers(repo, commit, "Invariant-Scope")
    if not claimed:
        raise InvariantError(f"TRAILER: missing Invariant-Scope on {commit}", exit_code=1, code="invalid_trailer")
    domain_ids = {str(row.get("id")) for row in domains(repo)}
    for domain in git.trailers(repo, commit, "Invariant-Domain"):
        if domain not in domain_ids:
            raise InvariantError(f"TRAILER: unknown Invariant-Domain {domain}", exit_code=1, code="invalid_trailer")
    architecture = {
        locator
        for row in [*domains(repo), *contracts(repo)]
        for locator in architecture_refs(row.get("architecture", row.get("material")))
    }
    architecture.update(
        record.document
        for record in semantic_records(repo)
        if record.status == "active" and record.document.startswith("architecture:")
    )
    for review in git.trailers(repo, commit, "Invariant-Architecture"):
        if not review.startswith("architecture:"):
            raise InvariantError(f"TRAILER: invalid Invariant-Architecture {review}", exit_code=1)
        if review not in architecture:
            raise InvariantError(f"TRAILER: unreferenced Invariant-Architecture {review}", exit_code=1)
    parent = git.resolve(repo, f"{commit}^")
    changed = git.changed_paths(repo, parent, commit) if parent else git.run(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit], cwd=repo
    ).stdout.splitlines()
    bad: list[str] = []
    for path in changed:
        if path == ".invariant" or path.startswith(".invariant/"):
            continue
        top = path.split("/", 1)[0]
        if top in TEST_DIRECTORIES:
            continue
        ids = derived_scopes(repo, path)
        if not any(
            claim == item or claim.startswith(item + ".") or item.startswith(claim + ".")
            for claim in claimed
            for item in ids
        ):
            bad.append(path)
    if bad:
        raise InvariantError(f"TRAILER: claimed scopes do not contain: {' '.join(bad)}", exit_code=1)
    return [f"TRAILER: OK {' '.join(claimed)}"]
