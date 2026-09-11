from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import git
from invariant.mechanics.documents import dump_config_yaml, load_config_yaml, parse_config_yaml


CONFIG_PATH = Path(".invariant/config.yml")
SETTABLE_KEYS = {
    "authority",
    "execution",
    "integration_branch",
    "push_remote",
    "adapters.intent_brief",
}
CODING_AGENT_CHOICES = {"claude", "codex"}


def initialized(repo: Path) -> bool:
    return (repo / CONFIG_PATH).is_file()


def require_initialized(repo: Path) -> None:
    if initialized(repo):
        return
    raise Blocked(
        "Invariant: initialize this repository before running managed commands",
        code="not_initialized",
        lines=["STATUS: not initialized", "NEXT: invariant init"],
    )


@dataclass(frozen=True)
class AdapterOptions:
    values: tuple[tuple[str, bool], ...] = (("intent_brief", False),)

    @property
    def enabled(self) -> tuple[str, ...]:
        return tuple(name for name, active in self.values if active)

    def is_enabled(self, name: str) -> bool:
        return any(candidate == name and active for candidate, active in self.values)

    def as_dict(self) -> dict[str, str]:
        return {name: "on" if active else "off" for name, active in self.values}


@dataclass(frozen=True)
class VerifierRunner:
    name: str
    command: tuple[str, ...]
    cwd: str = "."
    cache: str = "never"
    timeout: int = 0


DEFAULT_VERIFIER_TIMEOUT = 300


@dataclass(frozen=True)
class VerificationOptions:
    runners: tuple[VerifierRunner, ...] = ()
    timeout: int = DEFAULT_VERIFIER_TIMEOUT

    def named(self, name: str) -> VerifierRunner | None:
        return next((runner for runner in self.runners if runner.name == name), None)


@dataclass(frozen=True)
class Config:
    authority: str
    execution: str
    integration_branch: str
    integration_branch_setting: str
    push_remote: str
    source: str
    branch_source: str
    unborn: bool
    adapters: AdapterOptions
    verification: VerificationOptions


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


def _from_raw(
    repo: Path,
    raw: Any,
    *,
    source: str,
    fallback_branch: str,
    fallback_source: str,
) -> Config:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise InvariantError("Invariant: .invariant/config.yml must declare version: 1")
    allowed = {
        "version",
        "authority",
        "execution",
        "integration_branch",
        "push_remote",
        "adapters",
        "verification",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InvariantError(f"Invariant: .invariant/config.yml has unknown field '{unknown[0]}'")
    authority = raw.get("authority", "agent")
    if authority not in {"agent", "human"}:
        raise InvariantError(
            f"Invariant: .invariant/config.yml has invalid authority '{authority}' (use agent or human)"
        )
    execution = raw.get("execution", "auto")
    if execution not in {"auto", "assisted"}:
        raise InvariantError(
            f"Invariant: .invariant/config.yml has invalid execution '{execution}' (use auto or assisted)"
        )
    push_remote = raw.get("push_remote", "off")
    if push_remote not in {"on", "off"}:
        raise InvariantError(
            f"Invariant: .invariant/config.yml has invalid push_remote '{push_remote}' (use on or off)"
        )
    adapters_raw = raw.get("adapters", {"intent_brief": "off"})
    if not isinstance(adapters_raw, dict):
        raise InvariantError("Invariant: .invariant/config.yml adapters must be a mapping")
    adapter_values: list[tuple[str, bool]] = []
    for name, enabled in sorted(adapters_raw.items()):
        if not isinstance(name, str) or not git.valid_id(name):
            raise InvariantError(f"Invariant: invalid adapter id '{name}'")
        if not isinstance(enabled, str) or enabled not in {"on", "off"}:
            raise InvariantError(f"Invariant: adapters.{name} must be on or off")
        adapter_values.append((name, enabled == "on"))
    if "intent_brief" not in adapters_raw:
        adapter_values.append(("intent_brief", False))
        adapter_values.sort()
    adapters = AdapterOptions(tuple(adapter_values))
    verification_raw = raw.get("verification", {})
    if not isinstance(verification_raw, dict):
        raise InvariantError("Invariant: .invariant/config.yml verification must be a mapping")
    verification_unknown = sorted(set(verification_raw) - {"runners", "timeout"})
    if verification_unknown:
        raise InvariantError(
            f"Invariant: .invariant/config.yml has unknown verification field '{verification_unknown[0]}'"
        )
    default_timeout = verification_raw.get("timeout", DEFAULT_VERIFIER_TIMEOUT)
    if not isinstance(default_timeout, int) or isinstance(default_timeout, bool) or default_timeout <= 0:
        raise InvariantError(
            "Invariant: verification timeout must be a positive integer number of seconds"
        )
    runners_raw = verification_raw.get("runners", {})
    if not isinstance(runners_raw, dict):
        raise InvariantError("Invariant: verification.runners must be a mapping")
    runners: list[VerifierRunner] = []
    for name, runner_raw in sorted(runners_raw.items()):
        if not isinstance(name, str) or not git.valid_id(name):
            raise InvariantError(f"Invariant: invalid verifier runner name '{name}'")
        if not isinstance(runner_raw, dict):
            raise InvariantError(f"Invariant: verification runner '{name}' must be a mapping")
        runner_unknown = sorted(set(runner_raw) - {"command", "cwd", "cache", "timeout"})
        if runner_unknown:
            raise InvariantError(
                f"Invariant: verification runner '{name}' has unknown field '{runner_unknown[0]}'"
            )
        command = runner_raw.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item for item in command)
        ):
            raise InvariantError(
                f"Invariant: verification runner '{name}' command must be a non-empty string list"
            )
        cwd = runner_raw.get("cwd", ".")
        if (
            not isinstance(cwd, str)
            or not cwd
            or Path(cwd).is_absolute()
            or ".." in Path(cwd).parts
        ):
            raise InvariantError(
                f"Invariant: verification runner '{name}' cwd must stay inside the repository"
            )
        cache = runner_raw.get("cache", "never")
        if cache not in {"never", "exact-tree"}:
            raise InvariantError(
                f"Invariant: verification runner '{name}' cache must be never or exact-tree"
            )
        timeout = runner_raw.get("timeout", 0)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
            raise InvariantError(
                f"Invariant: verification runner '{name}' timeout must be a non-negative integer"
            )
        runners.append(VerifierRunner(name, tuple(command), cwd, cache, timeout))
    verification = VerificationOptions(tuple(runners), default_timeout)
    configured = raw.get("integration_branch", "auto")
    if not isinstance(configured, str) or not configured:
        raise InvariantError("Invariant: integration_branch must be auto or a non-empty branch name")
    if configured == "auto":
        branch = fallback_branch
        branch_source = fallback_source
    else:
        if git.run(["check-ref-format", "--branch", configured], cwd=repo, check=False).returncode:
            raise InvariantError(f"Invariant: invalid integration branch '{configured}'")
        branch = configured
        branch_source = "config"
    return _finish(
        repo,
        authority,
        execution,
        branch,
        configured,
        push_remote,
        source,
        branch_source,
        adapters,
        verification,
    )


def resolve(repo: Path) -> Config:
    config_path = repo / CONFIG_PATH
    if not config_path.exists():
        require_initialized(repo)
    if not config_path.is_file():
        raise InvariantError("Invariant: .invariant/config.yml is not a regular file")
    raw = load_config_yaml(config_path)
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
        raise InvariantError(f"Invariant: configuration ground '{ref}' does not resolve")
    result = git.run(["show", f"{ref}:{CONFIG_PATH.as_posix()}"], cwd=repo, check=False)
    if result.returncode:
        raise Blocked(
            f"Invariant: initialization is not committed on integration branch "
            f"'{integration_branch}'",
            code="initialization_not_committed",
            lines=[
                "STATUS: initialization not committed",
                "NEXT: commit the initialization, then rerun the command",
            ],
        )
    try:
        raw = parse_config_yaml(result.stdout)
    except yaml.YAMLError as exc:
        raise InvariantError(
            f"Invariant: invalid YAML in {CONFIG_PATH.as_posix()} at {ref}: {exc}",
            code="invalid_yaml",
        ) from exc
    return _from_raw(
        repo,
        raw,
        source=f"{CONFIG_PATH.as_posix()} at {ref}",
        fallback_branch=integration_branch,
        fallback_source="accepted",
    )


def initialize(
    repo: Path,
    *,
    authority: str | None = None,
    execution: str | None = None,
    integration_branch: str | None = None,
    push_remote: str | None = None,
    intent_brief: bool | None = None,
    overwrite: bool = False,
) -> list[str]:
    path = repo / CONFIG_PATH
    if path.exists() and not overwrite:
        raise InvariantError(f"Invariant: {CONFIG_PATH.as_posix()} already exists", code="config_exists")
    branch_setting = integration_branch or "auto"
    if branch_setting == "auto":
        fallback_branch, fallback_source = _current(repo)
    else:
        fallback_branch, fallback_source = branch_setting, "config"
    document: dict[str, Any] = {
        "version": 1,
        "authority": authority if authority is not None else "agent",
        "execution": execution if execution is not None else "auto",
        "integration_branch": branch_setting,
        "push_remote": push_remote if push_remote is not None else "off",
        "adapters": {"intent_brief": "on" if intent_brief is True else "off"},
    }
    _from_raw(
        repo,
        document,
        source=CONFIG_PATH.as_posix(),
        fallback_branch=fallback_branch,
        fallback_source=fallback_source,
    )
    dump_config_yaml(path, document)
    action = "replaced" if overwrite else "created"
    return [f"CONFIG: {action} {CONFIG_PATH.as_posix()}", *lines(resolve(repo))]


def set_value(repo: Path, key: str, value: str) -> list[str]:
    if key not in SETTABLE_KEYS:
        raise InvariantError(f"Invariant: configuration key '{key}' is not settable", code="invalid_config_key")
    path = repo / CONFIG_PATH
    require_initialized(repo)
    current = resolve(repo)
    raw = load_config_yaml(path)
    if not isinstance(raw, dict):
        raise InvariantError("Invariant: .invariant/config.yml must contain a mapping")
    document = dict(raw)

    if key in {"authority", "execution"}:
        choices = {"authority": {"agent", "human"}, "execution": {"auto", "assisted"}}
        if value not in choices[key]:
            expected = " or ".join(sorted(choices[key]))
            raise InvariantError(f"Invariant: {key} must be {expected}", code="invalid_config_value")
        document[key] = value
    elif key == "integration_branch":
        if value != "auto" and git.run(["check-ref-format", "--branch", value], cwd=repo, check=False).returncode:
            raise InvariantError(f"Invariant: invalid integration branch '{value}'", code="invalid_config_value")
        document[key] = value
    elif key == "push_remote":
        if value not in {"on", "off"}:
            raise InvariantError("Invariant: push_remote must be on or off", code="invalid_config_value")
        document[key] = value
    elif key.startswith("adapters."):
        if value not in {"on", "off"}:
            raise InvariantError(f"Invariant: {key} must be on or off", code="invalid_config_value")
        adapter_values = document.get("adapters", {})
        if not isinstance(adapter_values, dict):
            raise InvariantError("Invariant: .invariant/config.yml adapters must be a mapping")
        adapter_values = dict(adapter_values)
        adapter_values[key.removeprefix("adapters.")] = value
        document["adapters"] = adapter_values
    _from_raw(
        repo,
        document,
        source=CONFIG_PATH.as_posix(),
        fallback_branch=current.integration_branch,
        fallback_source=current.branch_source,
    )
    dump_config_yaml(path, document)
    return [f"CONFIG: set {key}={value}", *lines(resolve(repo))]


def _finish(
    repo: Path,
    authority: str,
    execution: str,
    branch: str,
    branch_setting: str,
    push_remote: str,
    source: str,
    branch_source: str,
    adapters: AdapterOptions,
    verification: VerificationOptions,
) -> Config:
    unborn = not git.branch_exists(repo, branch)
    if unborn:
        symbolic = git.current_branch(repo)
        allowed_unborn = (
            symbolic == branch and git.resolve(repo, "HEAD") is None
        ) or (
            os.environ.get("INVARIANT_ALLOW_UNBORN") == "1"
            and os.environ.get("INVARIANT_INTEGRATION_TARGET") == branch
        )
        if not allowed_unborn:
            raise InvariantError(f"Invariant: configured integration branch '{branch}' does not exist locally")
    return Config(
        authority,
        execution,
        branch,
        branch_setting,
        push_remote,
        source,
        branch_source,
        unborn,
        adapters,
        verification,
    )


def lines(config: Config) -> list[str]:
    output = [
        "version: 1",
        f"authority: {config.authority}",
        f"execution: {config.execution}",
        f"integration_branch: {config.integration_branch_setting}",
        f"push_remote: {config.push_remote}",
        f"source: {config.source}",
        f"integration_branch_resolved: {config.integration_branch}",
        f"branch_source: {config.branch_source}",
        *[
            f"adapter_{name}: {'on' if enabled else 'off'}"
            for name, enabled in config.adapters.values
        ],
    ]
    if config.unborn:
        output.append("integration_branch_unborn: true")
    for runner in config.verification.runners:
        output.append(
            f"verification_runner: {runner.name} cwd={runner.cwd} cache={runner.cache}"
        )
    return output
