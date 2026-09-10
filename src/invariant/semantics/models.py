from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import UsageError
from invariant.protocol import BoundaryDisposition


def _load_yaml(path: str | Path) -> Any:
    source = Path(path)
    try:
        return yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"Invariant: no such file '{source}'") from None
    except yaml.YAMLError as exc:
        raise UsageError(f"Invariant: invalid YAML in {source}: {exc}") from exc


def string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise UsageError(f"{field_name} must be a list of non-empty strings")
    return sorted(set(value))


@dataclass(frozen=True)
class Boundary:
    value: BoundaryDisposition

    @property
    def disposition(self) -> str:
        return self.value.value

    @classmethod
    def from_value(cls, value: Any) -> "Boundary":
        if not isinstance(value, dict):
            raise UsageError("assessment boundary must be a mapping")
        unknown = sorted(set(value) - {"disposition"})
        if unknown:
            raise UsageError(f"assessment boundary has unknown field '{unknown[0]}'")
        raw_disposition = value.get("disposition")
        if not isinstance(raw_disposition, str):
            raise UsageError("assessment boundary requires a disposition")
        try:
            disposition = BoundaryDisposition.parse(
                raw_disposition, allow_unresolved=False
            )
        except UsageError as exc:
            raise UsageError("assessment has an invalid boundary disposition") from exc
        return cls(disposition)


@dataclass(frozen=True)
class Assessment:
    version: int
    goal_digest: str
    paths: list[str]
    interfaces: list[str]
    domains: list[str]
    boundary: Boundary
    governance: list[str]
    architecture_reviews: list[str]
    checks: list[str]
    allow_open: bool = False
    prose: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Assessment":
        raw = _load_yaml(path)
        if not isinstance(raw, dict):
            raise UsageError("assessment must be a YAML mapping")
        allowed = {
            "version",
            "goal_digest",
            "paths",
            "interfaces",
            "domains",
            "boundary",
            "governance",
            "architecture_reviews",
            "checks",
            "allow_open",
            "prose",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"assessment has unknown field '{unknown[0]}'")
        if raw.get("version") != 1:
            raise UsageError("assessment must declare version: 1")
        required = {
            "goal_digest",
            "paths",
            "interfaces",
            "domains",
            "boundary",
            "governance",
            "architecture_reviews",
            "checks",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise UsageError(f"assessment is missing required field '{missing[0]}'")
        goal_digest = raw.get("goal_digest")
        if not isinstance(goal_digest, str) or not goal_digest:
            raise UsageError("assessment requires goal_digest")
        prose = raw.get("prose", "")
        if not isinstance(prose, str):
            raise UsageError("assessment prose must be text")
        allow_open = raw.get("allow_open", False)
        if not isinstance(allow_open, bool):
            raise UsageError("assessment allow_open must be true or false")
        return cls(
            version=1,
            goal_digest=goal_digest,
            paths=string_list(raw.get("paths"), "assessment paths"),
            interfaces=string_list(raw.get("interfaces"), "assessment interfaces"),
            domains=string_list(raw.get("domains"), "assessment domains"),
            boundary=Boundary.from_value(raw.get("boundary")),
            governance=string_list(raw.get("governance"), "assessment governance"),
            architecture_reviews=string_list(
                raw.get("architecture_reviews"), "assessment architecture_reviews"
            ),
            checks=string_list(raw.get("checks"), "assessment checks"),
            allow_open=allow_open,
            prose=prose,
        )
