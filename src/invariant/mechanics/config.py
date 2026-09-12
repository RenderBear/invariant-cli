"""Tracked protocol-v1 policy with authority separate from execution."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import git
from invariant.mechanics.documents import dump_config_yaml, load_config_yaml, parse_config_yaml
from invariant.protocol import PROTOCOL_VERSION


CONFIG_PATH = Path(".invariant/config.yml")
@dataclass(frozen=True)
class IntentAuthority:
    suppliers: tuple[str, ...] = ("user",)

    def permits(self, locator: str) -> bool:
        return locator.partition(":")[0] in self.suppliers


@dataclass(frozen=True)
class ResolutionAuthority:
    delegation: str = "secondary-agent"


@dataclass(frozen=True)
class AuthorityPolicy:
    intent: IntentAuthority = IntentAuthority()
    resolution: ResolutionAuthority = ResolutionAuthority()


@dataclass(frozen=True)
class ExecutionPolicy:
    transitions: str = "auto"


@dataclass(frozen=True)
class ParallelismPolicy:
    maximum: str | int = "auto"

    def limit(self, host_capacity: int | None = None) -> int:
        configured = 32 if self.maximum == "auto" else int(self.maximum)
        return min(configured, host_capacity or configured)


@dataclass(frozen=True)
class Config:
    authority: AuthorityPolicy
    execution: ExecutionPolicy
    integration_branch: str
    integration_branch_setting: str
    publication: str
    parallelism: ParallelismPolicy
    source: str
    branch_source: str
    unborn: bool


def initialized(repo: Path) -> bool:
    return (repo / CONFIG_PATH).is_file()


def require_initialized(repo: Path) -> None:
    if not initialized(repo):
        raise Blocked(
            "Invariant: initialize this repository before running governed commands",
            code="not_initialized",
            lines=["STATUS: not initialized", "NEXT: invariant init"],
        )


def _current(repo: Path) -> tuple[str, str]:
    captured = os.environ.get("INVARIANT_INTEGRATION_TARGET")
    if captured:
        return captured, "captured"
    branch = git.current_branch(repo)
    if not branch:
        raise InvariantError(
            "Invariant: integration_branch is not configured and HEAD is detached",
            code="missing_integration_target",
        )
    return branch, "current"


def _mapping(value: object, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvariantError(f"Invariant: {label} must be a mapping", code="invalid_policy")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InvariantError(
            f"Invariant: {label} has unknown field '{unknown[0]}'", code="invalid_policy"
        )
    return value


def _from_raw(
    repo: Path,
    raw: Any,
    *,
    source: str,
    fallback_branch: str,
    fallback_source: str,
) -> Config:
    if not isinstance(raw, dict) or raw.get("version") != PROTOCOL_VERSION:
        raise InvariantError(
            f"Invariant: .invariant/config.yml must declare version: {PROTOCOL_VERSION}",
            code="invalid_policy",
        )
    allowed = {
        "version",
        "authority",
        "execution",
        "integration_branch",
        "publication",
        "parallelism",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InvariantError(
            f"Invariant: .invariant/config.yml has unknown field '{unknown[0]}'",
            code="invalid_policy",
        )

    authority_raw = _mapping(raw.get("authority", {}), "authority", {"intent", "resolution"})
    intent_raw = _mapping(
        authority_raw.get("intent", {}), "authority.intent", {"suppliers"}
    )
    suppliers = intent_raw.get("suppliers", ["user"])
    if (
        not isinstance(suppliers, list)
        or not suppliers
        or any(item not in {"user", "policy"} for item in suppliers)
    ):
        raise InvariantError(
            "Invariant: authority.intent.suppliers must be a non-empty list containing user and/or policy",
            code="invalid_policy",
        )
    intent = IntentAuthority(tuple(dict.fromkeys(suppliers)))

    resolution_raw = _mapping(
        authority_raw.get("resolution", {}),
        "authority.resolution",
        {"delegation"},
    )
    delegation = resolution_raw.get("delegation", "secondary-agent")
    if delegation not in {"secondary-agent", "user"}:
        raise InvariantError(
            "Invariant: authority.resolution.delegation must be secondary-agent or user",
            code="invalid_policy",
        )
    authority = AuthorityPolicy(intent, ResolutionAuthority(delegation))

    execution_raw = _mapping(raw.get("execution", {}), "execution", {"transitions"})
    transitions = execution_raw.get("transitions", "auto")
    if transitions not in {"auto", "assisted"}:
        raise InvariantError(
            "Invariant: execution.transitions must be auto or assisted",
            code="invalid_policy",
        )
    execution = ExecutionPolicy(transitions)

    publication = raw.get("publication", "off")
    if publication not in {"on", "off"}:
        raise InvariantError(
            "Invariant: publication must be on or off", code="invalid_policy"
        )

    parallelism_raw = _mapping(raw.get("parallelism", {}), "parallelism", {"maximum"})
    maximum = parallelism_raw.get("maximum", "auto")
    if maximum != "auto" and (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 1 <= maximum <= 32
    ):
        raise InvariantError(
            "Invariant: parallelism.maximum must be auto or an integer from 1 to 32",
            code="invalid_policy",
        )
    parallelism = ParallelismPolicy(maximum)

    configured = raw.get("integration_branch", "auto")
    if not isinstance(configured, str) or not configured:
        raise InvariantError(
            "Invariant: integration_branch must be auto or a non-empty branch name",
            code="invalid_policy",
        )
    if configured == "auto":
        branch, branch_source = fallback_branch, fallback_source
    else:
        if git.run(["check-ref-format", "--branch", configured], cwd=repo, check=False).returncode:
            raise InvariantError(
                f"Invariant: invalid integration branch '{configured}'", code="invalid_policy"
            )
        branch, branch_source = configured, "config"

    unborn = not git.branch_exists(repo, branch)
    if unborn:
        symbolic = git.current_branch(repo)
        allowed_unborn = (symbolic == branch and git.resolve(repo, "HEAD") is None) or (
            os.environ.get("INVARIANT_ALLOW_UNBORN") == "1"
            and os.environ.get("INVARIANT_INTEGRATION_TARGET") == branch
        )
        if not allowed_unborn:
            raise InvariantError(
                f"Invariant: configured integration branch '{branch}' does not exist locally",
                code="invalid_policy",
            )
    return Config(
        authority,
        execution,
        branch,
        configured,
        publication,
        parallelism,
        source,
        branch_source,
        unborn,
    )


def resolve(repo: Path) -> Config:
    require_initialized(repo)
    path = repo / CONFIG_PATH
    raw = load_config_yaml(path)
    branch, branch_source = _current(repo)
    return _from_raw(
        repo,
        raw,
        source=CONFIG_PATH.as_posix(),
        fallback_branch=branch,
        fallback_source=branch_source,
    )


def resolve_at(repo: Path, ref: str, integration_branch: str) -> Config:
    if not git.resolve(repo, ref):
        raise InvariantError(
            f"Invariant: configuration ground '{ref}' does not resolve", code="missing_object"
        )
    result = git.run(["show", f"{ref}:{CONFIG_PATH.as_posix()}"], cwd=repo, check=False)
    if result.returncode:
        raise Blocked(
            f"Invariant: initialization is not committed on '{integration_branch}'",
            code="not_initialized",
        )
    try:
        raw = parse_config_yaml(result.stdout)
    except yaml.YAMLError as exc:
        raise InvariantError(
            f"Invariant: invalid configuration at {ref}: {exc}", code="invalid_policy"
        ) from exc
    return _from_raw(
        repo,
        raw,
        source=f"{CONFIG_PATH.as_posix()} at {ref}",
        fallback_branch=integration_branch,
        fallback_source="accepted",
    )


def default_document(
    *,
    intent_suppliers: tuple[str, ...] = ("user",),
    resolution_delegation: str = "secondary-agent",
    execution_transitions: str = "auto",
    integration_branch: str = "auto",
    publication: str = "off",
    parallelism_maximum: str | int = "auto",
) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "authority": {
            "intent": {"suppliers": list(intent_suppliers)},
            "resolution": {"delegation": resolution_delegation},
        },
        "execution": {"transitions": execution_transitions},
        "integration_branch": integration_branch,
        "publication": publication,
        "parallelism": {"maximum": parallelism_maximum},
    }


def initialize(repo: Path, **values: Any) -> list[str]:
    path = repo / CONFIG_PATH
    if path.exists():
        raise InvariantError(
            f"Invariant: {CONFIG_PATH.as_posix()} already exists", code="config_exists"
        )
    document = default_document(**values)
    fallback = document["integration_branch"]
    if fallback == "auto":
        fallback, branch_source = _current(repo)
    else:
        branch_source = "config"
    _from_raw(
        repo,
        document,
        source=CONFIG_PATH.as_posix(),
        fallback_branch=fallback,
        fallback_source=branch_source,
    )
    dump_config_yaml(path, document)
    exclude = git.common_dir(repo) / "info/exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    ignored = "/.invariant/runtime/"
    current_excludes = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ignored not in current_excludes.splitlines():
        separator = "" if not current_excludes or current_excludes.endswith("\n") else "\n"
        exclude.write_text(current_excludes + separator + ignored + "\n", encoding="utf-8")
    return [f"CONFIG: created {CONFIG_PATH.as_posix()}", *lines(resolve(repo))]


def lines(value: Config) -> list[str]:
    return [
        f"version: {PROTOCOL_VERSION}",
        f"authority.intent.suppliers: {','.join(value.authority.intent.suppliers)}",
        f"authority.resolution.delegation: {value.authority.resolution.delegation}",
        f"execution.transitions: {value.execution.transitions}",
        f"integration_branch: {value.integration_branch_setting}",
        f"publication: {value.publication}",
        f"parallelism.maximum: {value.parallelism.maximum}",
        f"source: {value.source}",
        f"integration_branch_resolved: {value.integration_branch}",
        f"branch_source: {value.branch_source}",
    ]
