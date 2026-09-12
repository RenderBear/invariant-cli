"""The planning context: everything Invariant selected, in the form a planner or worker needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from invariant.governance import GovernanceSelection, GovernanceStore
from invariant.governance.compiler import ObligationSet
from invariant.mechanics import git

TREE_LIMIT = 400


def _canonical_sections(store: GovernanceStore, record: Any, ref: str) -> list[dict[str, str]]:
    locators: list[str] = []
    document = record.data.get("document")
    if isinstance(document, str):
        locators.append(document)
    locators.extend(record.strings("architecture"))
    locators.extend(
        item for item in record.strings("material") if item.startswith("architecture:")
    )
    sections = []
    for locator in dict.fromkeys(locators):
        try:
            sections.append({"locator": locator, "text": store._architecture_section(locator, ref)})
        except Exception:  # unresolved sections were already rejected at load; keep planning robust
            continue
    return sections


def tree_under(repo: Path, ref: str, paths: Mapping[str, Any] | list[str]) -> list[str]:
    values = [str(path).removeprefix("repo:").strip("/") for path in paths]
    values = [value for value in values if value and value != "."]
    if not values:
        return []
    listing = git.run(
        ["ls-tree", "-r", "--name-only", ref, "--", *values], cwd=repo, check=False
    ).stdout.splitlines()
    return listing[:TREE_LIMIT]


def build(
    repo: Path,
    *,
    ref: str,
    selection: GovernanceSelection,
    obligations: ObligationSet,
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Selected records with prose, domain and contract coordinates, obligations, and the tree."""

    store = GovernanceStore(repo)
    records = []
    for record in selection.records:
        entry: dict[str, Any] = {
            "reference": record.reference,
            "kind": record.kind,
            "id": record.identifier,
            "authority": record.authority,
            "fields": {
                key: value
                for key, value in record.data.items()
                if key not in {"version", "id", "relations", "facets"}
            },
            "sections": _canonical_sections(store, record, ref),
        }
        records.append(entry)
    return {
        "records": records,
        "domains": [
            {"id": item["id"], "scope": item["fields"].get("scope", []), "interfaces": item["fields"].get("interfaces", []), "contracts": item["fields"].get("contracts", [])}
            for item in records
            if item["kind"] == "domain"
        ],
        "contracts": [
            {"id": item["id"], "between": item["fields"].get("between", []), "surfaces": item["fields"].get("surfaces", []), "verifies": item["fields"].get("verifies", [])}
            for item in records
            if item["kind"] == "contract"
        ],
        "obligations": obligations.as_dict(),
        "tree": tree_under(repo, ref, scope.get("paths", [])),
        "question": (
            "Does this intent split into mutually exclusive, contractually independent units? "
            "Propose more than one unit only when each unit has disjoint path claims, every "
            "contract has exactly one provider that its consumers depend on, and no serialized "
            "locator is reached by two units. Otherwise propose one unit over the declared reach."
        ),
    }


def routine_shape(selection: GovernanceSelection, obligations: ObligationSet) -> bool:
    """No contract, at most one domain, nothing serialized: nothing here can split independently."""

    kinds = [record.kind for record in selection.records]
    return (
        "contract" not in kinds
        and kinds.count("domain") <= 1
        and not obligations.serialize_on
    )


def guidance_lines(context: Mapping[str, Any]) -> list[str]:
    """Plain lines a worker or reviewer prompt carries so selected meaning is actually delivered."""

    lines: list[str] = []
    for record in context.get("records", []):
        fields = record.get("fields", {})
        summary = fields.get("responsibility") or fields.get("assertion") or fields.get("document") or ""
        lines.append(f"- {record['kind']} {record['id']}: {summary}")
        for name in ("scope", "surfaces", "applies_to", "verifies"):
            if fields.get(name):
                lines.append(f"    {name}: {', '.join(fields[name])}")
        for directive in fields.get("directives", []):
            lines.append(f"    rule: {directive}")
        for section in record.get("sections", []):
            text = section["text"].strip()
            if text:
                lines.append(f"    {section['locator']}:")
                lines.extend(f"      {row}" for row in text.splitlines()[:40])
    obligations = context.get("obligations", {})
    if obligations.get("required_verifiers"):
        lines.append(f"- verifiers that must pass: {', '.join(obligations['required_verifiers'])}")
    if obligations.get("required_reviews"):
        lines.append(f"- review required: {', '.join(obligations['required_reviews'])}")
    if obligations.get("serialize_on"):
        lines.append(f"- serialized: {', '.join(obligations['serialize_on'])}")
    if obligations.get("denied_capabilities"):
        lines.append(f"- denied: {', '.join(obligations['denied_capabilities'])}")
    return lines
