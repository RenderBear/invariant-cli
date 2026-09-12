from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml

from invariant.errors import InvariantError
from invariant.mechanics import git
from invariant.mechanics.documents import ConfigLoader
from invariant.protocol import (
    CapabilityName,
    DirectiveKind,
    PROTOCOL_VERSION,
    digest,
    require_authority_locator,
    require_id,
)


KINDS = ("semantic", "domain", "contract", "constraint")


def _strings(value: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise InvariantError(f"Invariant: {label} must be a list of non-empty strings", code="invalid_state")
    values = tuple(sorted(set(item.strip() for item in value)))
    if required and not values:
        raise InvariantError(f"Invariant: {label} cannot be empty", code="invalid_state")
    return values


@dataclass(frozen=True)
class Directive:
    identifier: str
    kind: DirectiveKind
    values: Mapping[str, Any]

    @classmethod
    def parse(cls, value: object, label: str) -> "Directive":
        if not isinstance(value, dict):
            raise InvariantError(f"Invariant: {label} must be a mapping", code="invalid_directive")
        try:
            identifier = require_id(value.get("id"), f"{label}.id")
            kind = DirectiveKind(str(value.get("kind")))
        except (ValueError, InvariantError) as exc:
            raise InvariantError(f"Invariant: invalid {label}: {exc}", code="invalid_directive") from exc
        shapes: dict[DirectiveKind, tuple[set[str], set[str]]] = {
            DirectiveKind.DENY_CAPABILITY: ({"id", "kind", "capability"}, {"capability"}),
            DirectiveKind.REQUIRE_RESOLUTION: (
                {"id", "kind", "capability", "resolver"}, {"capability", "resolver"}
            ),
            DirectiveKind.REQUIRE_REVIEW: ({"id", "kind", "mode"}, {"mode"}),
            DirectiveKind.REQUIRE_VERIFIER: ({"id", "kind", "locator"}, {"locator"}),
            DirectiveKind.SERIALIZE: ({"id", "kind", "on"}, {"on"}),
            DirectiveKind.LIMIT_PARALLELISM: ({"id", "kind", "maximum"}, {"maximum"}),
            DirectiveKind.REQUIRE_CONTAINMENT: (
                {"id", "kind", "capability", "enforcement"},
                {"capability", "enforcement"},
            ),
        }
        allowed, required = shapes[kind]
        if set(value) - allowed or required - set(value):
            raise InvariantError(
                f"Invariant: {label} does not match the closed {kind.value} shape",
                code="invalid_directive",
            )
        values = {name: value[name] for name in allowed - {"id", "kind"}}
        if "capability" in values:
            try:
                CapabilityName(str(values["capability"]))
            except ValueError as exc:
                raise InvariantError(
                    f"Invariant: {label} names unknown capability '{values['capability']}'",
                    code="unknown_capability",
                ) from exc
        if kind is DirectiveKind.REQUIRE_RESOLUTION and values["resolver"] not in {
            "user", "secondary-agent", "any-attributable"
        }:
            raise InvariantError(f"Invariant: {label}.resolver is invalid", code="invalid_directive")
        if kind is DirectiveKind.REQUIRE_REVIEW and values["mode"] not in {
            "attributable", "independent"
        }:
            raise InvariantError(f"Invariant: {label}.mode is invalid", code="invalid_directive")
        if kind is DirectiveKind.LIMIT_PARALLELISM and (
            not isinstance(values["maximum"], int)
            or isinstance(values["maximum"], bool)
            or not 1 <= values["maximum"] <= 32
        ):
            raise InvariantError(f"Invariant: {label}.maximum is invalid", code="invalid_directive")
        if kind is DirectiveKind.REQUIRE_CONTAINMENT and values["enforcement"] != "managed":
            raise InvariantError(f"Invariant: {label}.enforcement must be managed", code="invalid_directive")
        if kind is DirectiveKind.SERIALIZE:
            values["on"] = list(_strings(values["on"], f"{label}.on", required=True))
        return cls(identifier, kind, values)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.identifier, "kind": self.kind.value, **self.values}


@dataclass(frozen=True)
class Record:
    kind: str
    identifier: str
    authority: str
    data: Mapping[str, Any]
    directives: tuple[Directive, ...]
    digest: str
    path: str

    @property
    def reference(self) -> str:
        return f"record:{self.kind}:{self.identifier}@{self.digest}"

    def strings(self, name: str) -> tuple[str, ...]:
        value = self.data.get(name, ())
        return tuple(value) if isinstance(value, (list, tuple)) else ()


@dataclass(frozen=True)
class Governance:
    records: tuple[Record, ...]

    @property
    def digest(self) -> str:
        return digest([record.reference for record in self.records])

    def get(self, kind: str, identifier: str) -> Record | None:
        return next(
            (record for record in self.records if record.kind == kind and record.identifier == identifier),
            None,
        )


class GovernanceStore:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def load(self, ref: str | None = None) -> Governance:
        prefix = ".invariant/records"
        if ref:
            files = git.tree_text_files(self.repo, ref, prefix)
        else:
            root = self.repo / prefix
            files = {
                path.relative_to(self.repo).as_posix(): path.read_text(encoding="utf-8")
                for path in root.glob("*/*.yml")
                if path.is_file()
            } if root.exists() else {}
        records: list[Record] = []
        seen: set[tuple[str, str]] = set()
        for path, text in sorted(files.items()):
            parts = Path(path).parts
            if len(parts) != 4 or parts[:2] != (".invariant", "records") or parts[2] not in KINDS:
                raise InvariantError(f"Invariant: invalid record path '{path}'", code="unknown_record")
            kind = parts[2]
            try:
                raw = yaml.load(text, Loader=ConfigLoader)
            except yaml.YAMLError as exc:
                raise InvariantError(f"Invariant: invalid YAML in {path}: {exc}", code="invalid_state") from exc
            record = self._parse(kind, path, raw, ref)
            if Path(path).stem != record.identifier:
                raise InvariantError(
                    f"Invariant: record filename '{Path(path).stem}' does not equal id '{record.identifier}'",
                    code="invalid_state",
                )
            key = (kind, record.identifier)
            if key in seen:
                raise InvariantError(f"Invariant: duplicate record '{kind}:{record.identifier}'", code="invalid_state")
            seen.add(key)
            records.append(record)
        governance = Governance(tuple(records))
        self._validate_links(governance, ref)
        return governance

    def _parse(self, kind: str, path: str, raw: object, ref: str | None) -> Record:
        if not isinstance(raw, dict) or raw.get("version") != PROTOCOL_VERSION:
            raise InvariantError(
                f"Invariant: {path} must declare version: {PROTOCOL_VERSION}",
                code="invalid_state",
            )
        common = {"version", "id", "authority"}
        kind_fields = {
            "semantic": {
                "document", "status", "applies_to", "revisit_on", "verifies", "directives",
                "supersedes", "relations", "facets",
            },
            "domain": {"responsibility", "parent", "scope", "interfaces", "architecture", "contracts"},
            "contract": {"assertion", "between", "surfaces", "architecture", "verifies", "directives"},
            "constraint": {"assertion", "applies_to", "surfaces", "material", "verifies", "directives"},
        }[kind]
        unknown = sorted(set(raw) - common - kind_fields)
        if unknown:
            raise InvariantError(f"Invariant: {path} has unknown field '{unknown[0]}'", code="invalid_state")
        identifier = require_id(raw.get("id"), f"{path}.id")
        authority = require_authority_locator(raw.get("authority"), f"{path}.authority")
        required_text = {
            "semantic": ("document",),
            "domain": ("responsibility",),
            "contract": ("assertion",),
            "constraint": ("assertion",),
        }[kind]
        for field in required_text:
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise InvariantError(f"Invariant: {path}.{field} must be non-empty text", code="invalid_state")
        if kind == "semantic" and raw.get("status") not in {"active", "retired"}:
            raise InvariantError(
                f"Invariant: {path}.status must be active or retired",
                code="invalid_state",
            )
        required_lists = {
            "semantic": (),
            "domain": (),
            "contract": ("between", "surfaces", "architecture", "verifies"),
            "constraint": (),
        }[kind]
        list_fields = {
            "semantic": ("applies_to", "revisit_on", "verifies", "supersedes"),
            "domain": ("scope", "interfaces", "architecture", "contracts"),
            "contract": ("between", "surfaces", "architecture", "verifies"),
            "constraint": ("applies_to", "surfaces", "material", "verifies"),
        }[kind]
        normalized = dict(raw)
        for field in list_fields:
            normalized[field] = list(_strings(raw.get(field), f"{path}.{field}", required=field in required_lists))
        directives_raw = raw.get("directives", [])
        if not isinstance(directives_raw, list):
            raise InvariantError(f"Invariant: {path}.directives must be a list", code="invalid_directive")
        directives = tuple(
            Directive.parse(item, f"{path}.directives[{index}]")
            for index, item in enumerate(directives_raw)
        )
        ids = [directive.identifier for directive in directives]
        if len(ids) != len(set(ids)):
            raise InvariantError(f"Invariant: {path} has duplicate directive ids", code="invalid_directive")
        normalized["directives"] = [directive.as_dict() for directive in directives]
        if kind == "constraint" and not normalized.get("verifies") and not directives:
            raise InvariantError(
                f"Invariant: {path} requires a verifier or directive", code="invalid_state"
            )
        canonical = [
            self._architecture_section(locator, ref)
            for locator in (
                ([normalized["document"]] if kind == "semantic" else [])
                + list(normalized.get("architecture", []))
                + [
                    item
                    for item in normalized.get("material", [])
                    if item.startswith("architecture:")
                ]
            )
        ]
        record_digest = digest({"record": normalized, "canonical": canonical})
        return Record(kind, identifier, authority, normalized, directives, record_digest, path)

    def _validate_links(self, governance: Governance, ref: str | None) -> None:
        domains = {record.identifier for record in governance.records if record.kind == "domain"}
        contracts = {record.identifier for record in governance.records if record.kind == "contract"}
        parents: dict[str, str] = {}
        for record in governance.records:
            if record.kind == "domain":
                parent = record.data.get("parent")
                if parent is not None:
                    require_id(parent, f"{record.path}.parent")
                    if parent not in domains:
                        raise InvariantError(f"Invariant: {record.path} has missing parent '{parent}'", code="unresolved_locator")
                    parents[record.identifier] = parent
                for contract in record.strings("contracts"):
                    value = contract.removeprefix("contract:")
                    if value not in contracts:
                        raise InvariantError(f"Invariant: {record.path} has missing contract '{value}'", code="unresolved_locator")
            for locator in (*record.strings("applies_to"), *record.strings("between")):
                if locator.startswith("domain:") and locator.removeprefix("domain:") not in domains:
                    raise InvariantError(f"Invariant: unresolved locator '{locator}'", code="unresolved_locator")
            self._validate_record_locators(record, ref)
        for start in parents:
            seen: set[str] = set()
            current = start
            while current in parents:
                if current in seen:
                    raise InvariantError("Invariant: domain parent cycle", code="invalid_state")
                seen.add(current)
                current = parents[current]

    def _validate_record_locators(self, record: Record, ref: str | None) -> None:
        fields = (
            "applies_to", "revisit_on", "scope", "interfaces", "architecture",
            "contracts", "between", "surfaces", "material", "verifies",
        )
        for field in fields:
            for locator in record.strings(field):
                if field == "contracts" and ":" not in locator:
                    continue
                kind, separator, value = locator.partition(":")
                if not separator or kind not in {
                    "architecture", "repo", "interface", "domain", "contract",
                    "semantic", "capability", "command", "test", "runner", "audit",
                }:
                    raise InvariantError(
                        f"Invariant: invalid locator '{locator}' in {record.path}",
                        code="unresolved_locator",
                    )
                if kind == "capability":
                    try:
                        CapabilityName(value)
                    except ValueError as exc:
                        raise InvariantError(
                            f"Invariant: unknown capability locator '{locator}'",
                            code="unknown_capability",
                        ) from exc
                elif kind == "architecture":
                    self._architecture_section(locator, ref)
                elif kind in {"repo", "command", "test"}:
                    path = value.removeprefix("repo:")
                    if Path(path).is_absolute() or ".." in Path(path).parts:
                        raise InvariantError(
                            f"Invariant: locator escapes repository '{locator}'",
                            code="unresolved_locator",
                        )
                    if kind in {"command", "test"} and not self._file_exists(path, ref):
                        raise InvariantError(
                            f"Invariant: verifier does not resolve '{locator}'",
                            code="unresolved_locator",
                        )

    def _file_exists(self, path: str, ref: str | None) -> bool:
        if ref:
            return git.run(["cat-file", "-e", f"{ref}:{path}"], cwd=self.repo, check=False).returncode == 0
        return (self.repo / path).is_file()

    def _architecture_section(self, locator: str, ref: str | None) -> str:
        value = locator.removeprefix("architecture:")
        path, separator, anchor = value.rpartition("#")
        path = path.removeprefix("repo:")
        if (
            not separator
            or not path
            or not anchor
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise InvariantError(
                f"Invariant: invalid architecture locator '{locator}'",
                code="unresolved_locator",
            )
        if ref:
            result = git.run(["show", f"{ref}:{path}"], cwd=self.repo, check=False)
            if result.returncode:
                raise InvariantError(
                    f"Invariant: architecture path does not resolve '{locator}'",
                    code="unresolved_locator",
                )
            text = result.stdout
        else:
            source = self.repo / path
            if not source.is_file():
                raise InvariantError(
                    f"Invariant: architecture path does not resolve '{locator}'",
                    code="unresolved_locator",
                )
            text = source.read_text(encoding="utf-8")
        lines = text.splitlines()
        heading = re.compile(
            rf"^(?P<marks>#{{1,6}})\s+.+\s+\{{#{re.escape(anchor)}\}}\s*$"
        )
        for index, line in enumerate(lines):
            matched = heading.match(line)
            if not matched:
                continue
            level = len(matched.group("marks"))
            end = len(lines)
            for cursor in range(index + 1, len(lines)):
                next_heading = re.match(r"^(#{1,6})\s+", lines[cursor])
                if next_heading and len(next_heading.group(1)) <= level:
                    end = cursor
                    break
            return "\n".join(lines[index:end]).rstrip() + "\n"
        raise InvariantError(
            f"Invariant: architecture anchor does not resolve '{locator}'",
            code="unresolved_locator",
        )
