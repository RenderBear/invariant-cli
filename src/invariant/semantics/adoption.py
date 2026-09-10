from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from invariant.errors import UsageError
from invariant.semantics.domains import Domain
from invariant.semantics.records import SemanticRecord


RECORD_KINDS = {"semantic", "domain", "contract", "constraint"}
_IDENTIFIER_BODY = "[A-Za-z0-9][A-Za-z0-9._-]*"
_IDENTIFIER_PATTERN = f"^{_IDENTIFIER_BODY}$"
_ARCHITECTURE_PATTERN = "^architecture:[^\\s]+#[A-Za-z0-9][A-Za-z0-9._-]*$"
_AUTHORITY_PATTERN = (
    "^(user:task:|user:url:https?://|design:task:|design:url:https?://|"
    "architecture:repo:|design:repo:).+"
)
_MATERIAL_PATTERN = (
    "^(repo:|architecture:|adr:|schema:|task:|url:https?://).+"
)
_SURFACE_PATTERN = "^(repo:[^\\s]+|interface:[^\\s]+)$"
_VERIFIER_PATTERN = (
    f"^(command:[^\\s]+|test:[^\\s]+|schema:[^\\s]+|"
    f"runner:{_IDENTIFIER_BODY}#[^\\s]+)$"
)


def _string_list_schema(
    *,
    min_items: int = 0,
    pattern: str = "",
    description: str = "",
) -> dict[str, Any]:
    items: dict[str, Any] = {"type": "string", "minLength": 1}
    if pattern:
        items["pattern"] = pattern
    schema: dict[str, Any] = {
        "type": "array",
        "items": items,
    }
    if min_items:
        schema["minItems"] = min_items
    if description:
        schema["description"] = description
    return schema


def _record_variant(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"type": "string", "const": kind},
            "value": value,
        },
    }


def projected_record_schema() -> dict[str, Any]:
    """Closed record variants accepted by strict structured-output providers."""

    identifier = {
        "type": "string",
        "pattern": _IDENTIFIER_PATTERN,
    }
    text = {"type": "string", "minLength": 1}
    authority = {
        **text,
        "pattern": _AUTHORITY_PATTERN,
        "description": "Inspectable user:, design:, or architecture: authority locator.",
    }
    semantic = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "document",
            "authority",
            "status",
            "applies_to",
            "revisit_on",
            "verifies",
            "supersedes",
        ],
        "properties": {
            "id": identifier,
            "document": {
                **text,
                "pattern": _ARCHITECTURE_PATTERN,
                "description": "Canonical architecture:<markdown-path>#<anchor> locator.",
            },
            "authority": authority,
            "status": {
                "type": "string",
                "enum": ["active", "superseded"],
            },
            "applies_to": _string_list_schema(
                pattern=(
                    f"^(repo:[^\\s]+|interface:[^\\s]+|domain:{_IDENTIFIER_BODY})$"
                ),
                description="repo:, interface:, or domain: applicability locators.",
            ),
            "revisit_on": _string_list_schema(
                pattern=(
                    f"^(repo:[^\\s]+|interface:[^\\s]+|semantic:{_IDENTIFIER_BODY})$"
                ),
                description="repo:, interface:, or semantic: revisit locators.",
            ),
            "verifies": _string_list_schema(pattern=_VERIFIER_PATTERN),
            "supersedes": _string_list_schema(
                pattern=_IDENTIFIER_PATTERN,
                description="Bare semantic record IDs without a semantic: prefix.",
            ),
        },
    }
    domain = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "responsibility",
            "authority",
            "parent",
            "architecture",
            "contracts",
        ],
        "properties": {
            "id": identifier,
            "responsibility": text,
            "authority": authority,
            "parent": {
                "type": ["string", "null"],
                "pattern": _IDENTIFIER_PATTERN,
            },
            "architecture": _string_list_schema(pattern=_ARCHITECTURE_PATTERN),
            "contracts": _string_list_schema(
                pattern=_IDENTIFIER_PATTERN,
                description="Bare contract IDs without a contract: prefix.",
            ),
        },
    }
    contract = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "assertion",
            "authority",
            "between",
            "surfaces",
            "architecture",
            "material",
            "verifies",
        ],
        "properties": {
            "id": identifier,
            "assertion": text,
            "authority": authority,
            "between": _string_list_schema(
                min_items=2,
                pattern=_IDENTIFIER_PATTERN,
                description="Bare domain IDs without a domain: prefix.",
            ),
            "surfaces": _string_list_schema(
                min_items=1,
                pattern=_SURFACE_PATTERN,
            ),
            "architecture": _string_list_schema(pattern=_ARCHITECTURE_PATTERN),
            "material": _string_list_schema(pattern=_MATERIAL_PATTERN),
            "verifies": _string_list_schema(
                min_items=1,
                pattern=_VERIFIER_PATTERN,
            ),
        },
    }
    constraint = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "assertion",
            "authority",
            "applies_to",
            "surfaces",
            "material",
            "verifies",
        ],
        "properties": {
            "id": identifier,
            "assertion": text,
            "authority": authority,
            "applies_to": _string_list_schema(
                min_items=1,
                pattern=_IDENTIFIER_PATTERN,
                description="Bare domain IDs without a domain: prefix.",
            ),
            "surfaces": _string_list_schema(pattern=_SURFACE_PATTERN),
            "material": _string_list_schema(
                min_items=1,
                pattern=_MATERIAL_PATTERN,
            ),
            "verifies": _string_list_schema(pattern=_VERIFIER_PATTERN),
        },
    }
    return {
        "description": "One complete record projection whose shape matches its kind.",
        "anyOf": [
            _record_variant("semantic", semantic),
            _record_variant("domain", domain),
            _record_variant("contract", contract),
            _record_variant("constraint", constraint),
        ],
    }


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise UsageError(f"{label} must be a non-empty string list")
    return tuple(sorted(set(item.strip() for item in value)))


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"{label} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class ProjectedRecord:
    kind: str
    value: dict[str, Any]

    @property
    def identifier(self) -> str:
        return str(self.value.get("id") or "")

    @property
    def reference(self) -> str:
        return f"{self.kind}:{self.identifier}"

    @classmethod
    def parse(cls, raw: Any, label: str) -> "ProjectedRecord":
        if not isinstance(raw, dict):
            raise UsageError(f"{label} must be a mapping")
        unknown = sorted(set(raw) - {"kind", "value"})
        if unknown:
            raise UsageError(f"{label} has unknown field '{unknown[0]}'")
        kind = _text(raw.get("kind"), f"{label}.kind")
        if kind not in RECORD_KINDS:
            raise UsageError(
                f"{label}.kind must be semantic, domain, contract, or constraint"
            )
        value = raw.get("value")
        if not isinstance(value, dict):
            raise UsageError(f"{label}.value must be a record mapping")
        identifier = value.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier
        ):
            raise UsageError(f"{label}.value.id is invalid")
        if kind == "semantic":
            SemanticRecord.parse(value)
        elif kind == "domain":
            Domain.parse(value)
        return cls(kind, dict(value))


@dataclass(frozen=True)
class AdoptionMapping:
    findings: tuple[str, ...]
    records: tuple[ProjectedRecord, ...] = ()
    retained_as: str = ""
    deferred: str = ""
    unresolved: str = ""

    @classmethod
    def parse(cls, raw: Any, index: int) -> "AdoptionMapping":
        label = f"adoption mappings[{index}]"
        if not isinstance(raw, dict):
            raise UsageError(f"{label} must be a mapping")
        unknown = sorted(
            set(raw) - {"findings", "records", "retained_as", "deferred", "unresolved"}
        )
        if unknown:
            raise UsageError(f"{label} has unknown field '{unknown[0]}'")
        choices = [
            name
            for name in ("records", "retained_as", "deferred", "unresolved")
            if raw.get(name)
        ]
        if len(choices) != 1:
            raise UsageError(
                f"{label} must contain exactly one of records, retained_as, deferred, or unresolved"
            )
        findings = _strings(raw.get("findings"), f"{label}.findings")
        records: tuple[ProjectedRecord, ...] = ()
        retained_as = ""
        deferred = ""
        unresolved = ""
        if choices[0] == "records":
            values = raw.get("records")
            if not isinstance(values, list) or not values:
                raise UsageError(f"{label}.records must be a non-empty list")
            records = tuple(
                ProjectedRecord.parse(value, f"{label}.records[{record_index}]")
                for record_index, value in enumerate(values)
            )
        elif choices[0] == "retained_as":
            retained_as = _text(raw.get("retained_as"), f"{label}.retained_as")
            if not retained_as.startswith("discovery:"):
                raise UsageError(f"{label}.retained_as must use discovery:<id>")
        elif choices[0] == "deferred":
            deferred = _text(raw.get("deferred"), f"{label}.deferred")
        else:
            unresolved = _text(raw.get("unresolved"), f"{label}.unresolved")
        return cls(findings, records, retained_as, deferred, unresolved)

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"findings": list(self.findings)}
        if self.records:
            value["records"] = [
                {"kind": record.kind, "value": record.value} for record in self.records
            ]
        elif self.retained_as:
            value["retained_as"] = self.retained_as
        elif self.deferred:
            value["deferred"] = self.deferred
        else:
            value["unresolved"] = self.unresolved
        return value


@dataclass(frozen=True)
class AdoptionManifest:
    audit: str
    mappings: tuple[AdoptionMapping, ...]

    @classmethod
    def load(cls, source: str | Path) -> "AdoptionManifest":
        path = Path(source)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise UsageError(f"Invariant: no such file '{path}'") from None
        except yaml.YAMLError as exc:
            raise UsageError(f"Invariant: invalid YAML in {path}: {exc}") from exc
        return cls.parse(raw)

    @classmethod
    def parse(cls, raw: Any) -> "AdoptionManifest":
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise UsageError("adoption manifest must be a version-1 mapping")
        unknown = sorted(set(raw) - {"version", "audit", "mappings"})
        if unknown:
            raise UsageError(f"adoption manifest has unknown field '{unknown[0]}'")
        values = raw.get("mappings")
        if not isinstance(values, list) or not values:
            raise UsageError("adoption manifest requires mappings")
        return cls(
            _text(raw.get("audit"), "adoption manifest audit"),
            tuple(AdoptionMapping.parse(value, index) for index, value in enumerate(values)),
        )

    @classmethod
    def from_audit(
        cls,
        audit: str,
        findings: list[Any],
        selected: list[str],
    ) -> "AdoptionManifest":
        """Project authored audit records and flag only ambiguous findings for editing."""

        by_id = {
            str(finding.get("id")): finding
            for finding in findings
            if isinstance(finding, dict) and finding.get("id")
        }
        mappings: list[AdoptionMapping] = []
        for identifier in selected:
            finding = by_id.get(identifier, {})
            records = finding.get("records")
            if isinstance(records, list) and records:
                mappings.append(
                    AdoptionMapping(
                        (identifier,),
                        tuple(
                            ProjectedRecord.parse(
                                value,
                                f"audit finding '{identifier}'.records[{index}]",
                            )
                            for index, value in enumerate(records)
                        ),
                    )
                )
            else:
                mappings.append(
                    AdoptionMapping(
                        (identifier,),
                        unresolved=(
                            "Choose projected records, a retained discovery, or an explicit deferral."
                        ),
                    )
                )
        return cls(audit, tuple(mappings))

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "audit": self.audit,
            "mappings": [mapping.as_dict() for mapping in self.mappings],
        }


def schema() -> dict[str, Any]:
    string_list = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }
    record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"type": "string", "enum": sorted(RECORD_KINDS)},
            "value": {
                "type": "object",
                "description": "Complete candidate record, including its stable id.",
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "invariant://schemas/governance-adoption/v1",
        "title": "Invariant governance adoption manifest",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "audit", "mappings"],
        "properties": {
            "version": {"const": 1},
            "audit": {"type": "string", "minLength": 1},
            "mappings": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["findings"],
                    "properties": {
                        "findings": string_list,
                        "records": {"type": "array", "minItems": 1, "items": record},
                        "retained_as": {
                            "type": "string",
                            "pattern": "^discovery:[A-Za-z0-9][A-Za-z0-9._-]*$",
                        },
                        "deferred": {"type": "string", "minLength": 1},
                        "unresolved": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Generated draft marker; project refuses it until edited.",
                        },
                    },
                    "oneOf": [
                        {"required": ["records"]},
                        {"required": ["retained_as"]},
                        {"required": ["deferred"]},
                        {"required": ["unresolved"]},
                    ],
                },
            },
        },
    }


def example() -> dict[str, Any]:
    return {
        "version": 1,
        "audit": "audit-20260906T120000Z",
        "mappings": [
            {
                "findings": ["application-ownership"],
                "records": [
                    {
                        "kind": "domain",
                        "value": {
                            "id": "application",
                            "responsibility": "Owns application behavior and recovery.",
                            "authority": "user:task:governance#approval",
                        },
                    }
                ],
            },
            {
                "findings": ["legacy-recovery-gap"],
                "retained_as": "discovery:legacy-recovery-gap",
            },
        ],
    }
