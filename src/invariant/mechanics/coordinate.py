from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from invariant.errors import Blocked, InvariantError
from invariant.mechanics import config, git, governance
from invariant.mechanics.documents import dump_yaml, load_yaml


def runtime_root(repo: Path) -> Path:
    return git.primary_worktree(repo) / ".invariant" / "runtime"


def ensure_runtime(repo: Path) -> Path:
    runtime = runtime_root(repo)
    runtime.mkdir(parents=True, exist_ok=True)
    marker = runtime / ".gitignore"
    if not marker.exists():
        marker.write_text("*\n", encoding="utf-8")
    return runtime


def _plan_path(repo: Path, value: str) -> Path:
    if "/" in value:
        path = Path(value)
        return path if path.is_absolute() else repo / path
    return runtime_root(repo) / "plans" / f"{value}.yml"


def _related(first: str, second: str) -> bool:
    return governance.paths_related(first, second)


def validate_plan(repo: Path, value: str) -> list[str]:
    path = _plan_path(repo, value)
    if not path.is_file():
        raise InvariantError(f"Invariant: no plan '{value}'")
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise Blocked("PLAN: invalid — plan must be a mapping", code="invalid_plan")
    failures: list[str] = []
    identifier = raw.get("id")
    if raw.get("version") != 1:
        failures.append("version must be 1")
    if not isinstance(identifier, str) or not git.valid_id(identifier):
        failures.append(f"malformed id '{identifier}'")
    elif path.stem != identifier:
        failures.append(f"filename must be {identifier}.yml")
    if not raw.get("goal"):
        failures.append("missing goal")
    target = raw.get("integration_target")
    ground = raw.get("integration_ground")
    digest = raw.get("governing_digest")
    selected = governance.refs(raw.get("domains"))
    if not isinstance(target, str) or not target:
        failures.append("missing integration_target")
    elif not git.branch_exists(repo, target):
        failures.append(f"integration target '{target}' does not exist locally")
    if not isinstance(ground, str) or not ground:
        failures.append("missing integration_ground")
    elif not git.resolve(repo, ground):
        failures.append(f"integration ground '{ground}' is not a commit")
    elif isinstance(target, str) and git.branch_exists(repo, target) and not git.is_ancestor(repo, ground, f"refs/heads/{target}"):
        failures.append(f"integration ground is not an ancestor of '{target}'")
    if not isinstance(digest, str) or not digest:
        failures.append("missing governing_digest")
    else:
        try:
            actual = governance.digest(repo, selected)
            if actual != digest:
                failures.append(f"governing digest is stale (expected {digest}, current {actual})")
        except InvariantError as exc:
            failures.append(exc.message.removeprefix("Invariant: "))

    units_raw = raw.get("units")
    if not isinstance(units_raw, list):
        failures.append("units must be a list")
        units_raw = []
    units: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in units_raw:
        if not isinstance(item, dict):
            failures.append("unit must be a mapping")
            continue
        unit = item.get("id")
        if not isinstance(unit, str) or not git.valid_id(unit):
            failures.append(f"malformed unit id {unit}")
            continue
        if unit in units:
            failures.append(f"duplicate unit {unit}")
            continue
        units[unit] = item
        order.append(unit)
    if len(units) < 2:
        failures.append("coordination requires at least two units")

    dependency_sets: dict[str, set[str]] = {}
    for unit, item in units.items():
        if not item.get("objective"):
            failures.append(f"unit {unit} has no objective")
        paths = governance.refs(item.get("paths"))
        interfaces = governance.refs(item.get("interfaces"))
        claims = governance.refs(item.get("governance"))
        if not paths and not interfaces and not claims:
            failures.append(f"unit {unit} has no path, interface, or governance claim")
        verifiers = governance.refs(item.get("verifies"))
        if not verifiers:
            failures.append(f"unit {unit} has no verification")
        for path_claim in paths:
            if path_claim.startswith("/") or ".." in Path(path_claim).parts:
                failures.append(f"unit {unit} has unsafe path claim {path_claim}")
        for verifier in verifiers:
            if not verifier.startswith(("command:", "test:", "schema:", "runner:")):
                failures.append(f"unit {unit} has unsupported verifier {verifier}")
        dependencies = set(governance.refs(item.get("dependencies")))
        dependency_sets[unit] = dependencies
        for dependency in dependencies:
            if dependency == unit:
                failures.append(f"unit {unit} depends on itself")
            elif dependency not in units:
                failures.append(f"unit {unit} depends on missing unit {dependency}")
        for provided in governance.refs(item.get("provides")):
            if provided not in claims:
                failures.append(f"unit {unit} provides {provided} without claiming it as governance")

    def depends(unit: str, target_unit: str, visiting: set[str] | None = None) -> bool:
        visiting = visiting or set()
        if unit in visiting:
            return False
        visiting.add(unit)
        for dependency in dependency_sets.get(unit, set()):
            if dependency == target_unit or depends(dependency, target_unit, visiting.copy()):
                return True
        return False

    for unit in units:
        if depends(unit, unit):
            failures.append(f"dependency cycle includes {unit}")

    providers: dict[str, list[str]] = {}
    for unit, item in units.items():
        for provided in governance.refs(item.get("provides")):
            providers.setdefault(provided, []).append(unit)
    for contract, values in providers.items():
        if len(values) > 1:
            failures.append(f"multiple units provide {contract}")
    for consumer, item in units.items():
        for reliance in governance.refs(item.get("relies_on")):
            for provider in providers.get(reliance, []):
                if provider != consumer and not depends(consumer, provider):
                    failures.append(
                        f"unit {consumer} relies on {reliance} but does not depend on provider {provider}"
                    )

    for index, first in enumerate(order):
        for second in order[index + 1 :]:
            if depends(first, second) or depends(second, first):
                continue
            first_row, second_row = units[first], units[second]
            overlap = next(
                (
                    left
                    for left in governance.refs(first_row.get("paths"))
                    for right in governance.refs(second_row.get("paths"))
                    if _related(left, right)
                ),
                None,
            )
            if overlap:
                failures.append(f"unordered units {first} and {second} overlap at path {overlap}")
                continue
            for field, label in (("interfaces", "interface"), ("governance", "governance")):
                shared = set(governance.refs(first_row.get(field))).intersection(governance.refs(second_row.get(field)))
                if shared:
                    failures.append(
                        f"unordered units {first} and {second} overlap at {label} {sorted(shared)[0]}"
                    )
                    break
    if failures:
        raise Blocked(
            "PLAN: invalid — " + failures[0],
            code="invalid_plan",
            lines=[f"PLAN: invalid — {failure}" for failure in failures[1:]],
        )
    return [
        f"PLAN: valid — {len(units)} units, target and ground checked, dependencies acyclic, reliance ordered, unordered claims disjoint"
    ]


def _landed_units(repo: Path, target: str) -> set[str]:
    result = git.run(
        ["log", "--first-parent", target, "--format=%(trailers:key=Invariant-Unit,valueonly,separator=%x0a)"],
        cwd=repo,
        check=False,
    )
    return set(filter(None, result.stdout.splitlines()))


def plan_status(repo: Path, plan: str | None = None, *, pinned: bool = False) -> list[str]:
    plans_dir = runtime_root(repo) / "plans"
    if plan is None:
        files = sorted(plans_dir.glob("*.yml")) if plans_dir.is_dir() else []
        return ["plans:", *(f"  {path.stem}" for path in files)] if files else ["no plans"]
    path = plans_dir / f"{plan}.yml"
    if not path.is_file():
        raise Blocked(f"Invariant: no plan '{plan}'", code="missing_plan")
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise InvariantError(f"Invariant: invalid plan '{plan}'")
    target = str(raw.get("integration_target") or "HEAD")
    if not git.resolve(repo, target):
        target = "HEAD"
    landed = _landed_units(repo, target)
    units = [item for item in raw.get("units", []) if isinstance(item, dict)]
    leases = runtime_root(repo) / "leases"
    if pinned:
        output: list[str] = []
        for item in units:
            unit = str(item.get("id"))
            if unit in landed:
                output.append(f"PINNED: {unit} (landed)")
            elif (leases / f"{unit}.yml").is_file():
                output.append(f"PINNED: {unit} (leased)")
        return output
    output = [f"{'UNIT':<14} {'STATE':<13} DEPENDENCIES"]
    for item in units:
        unit = str(item.get("id"))
        dependencies = governance.refs(item.get("dependencies"))
        if unit in landed:
            status = "landed"
        elif (leases / f"{unit}.yml").is_file():
            status = "active"
        else:
            status = "dispatchable" if all(dep in landed for dep in dependencies) else "waiting"
        output.append(f"{unit:<14} {status:<13} {' '.join(dependencies) or '—'}")
    return output


def _duration(value: str) -> int:
    match = re.fullmatch(r"(\d+)([hms]?)", value)
    if not match:
        raise InvariantError(f"Invariant: invalid duration '{value}' (use 2h, 30m, or seconds)")
    multiplier = {"h": 3600, "m": 60, "s": 1, "": 1}[match.group(2)]
    return int(match.group(1)) * multiplier


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _lease_path(repo: Path, unit: str) -> Path:
    return runtime_root(repo) / "leases" / f"{unit}.yml"


def _lease(repo: Path, unit: str) -> dict[str, Any]:
    path = _lease_path(repo, unit)
    if not path.is_file():
        raise InvariantError(f"Invariant: no lease for '{unit}'")
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise InvariantError(f"Invariant: invalid lease for '{unit}'")
    return raw


def create_lease(
    repo: Path,
    unit: str,
    *,
    scope: str | None = None,
    paths: Iterable[str] = (),
    interfaces: Iterable[str] = (),
    governance_claims: Iterable[str] = (),
    domains: Iterable[str] = (),
    digest: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    task: str | None = None,
    owner: str | None = None,
    integration_target: str | None = None,
    duration: str = "2h",
) -> list[str]:
    path_values = sorted(set(paths))
    interface_values = sorted(set(interfaces))
    governance_values = sorted(set(governance_claims))
    domain_values = sorted(set(domains))
    if not path_values and not interface_values and not governance_values:
        raise InvariantError("Invariant: lease requires a path, interface, or governance claim")
    if domain_values:
        if not digest:
            raise InvariantError("Invariant: semantic domain claims require --digest")
        actual = governance.digest(repo, domain_values)
        if actual != digest:
            raise InvariantError(
                f"Invariant: lease governing digest is stale (expected {digest}, current {actual})"
            )
    path = _lease_path(repo, unit)
    if path.is_file():
        existing = _lease(repo, unit)
        raise InvariantError(
            f"Invariant: live lease for '{unit}' exists (owner {existing.get('owner')}) — renew or release it, never overwrite"
        )
    branch = branch or git.current_branch(repo) or ""
    owner = owner or branch
    worktree = worktree or str(repo)
    task = task or "local:unspecified"
    target = integration_target or config.resolve(repo).integration_branch
    if target and not git.branch_exists(repo, target):
        raise InvariantError(f"Invariant: integration target '{target}' does not exist locally")
    overlaps: list[str] = []
    directory = runtime_root(repo) / "leases"
    if directory.is_dir():
        for candidate in sorted(directory.glob("*.yml")):
            raw = load_yaml(candidate)
            if not isinstance(raw, dict):
                continue
            if (
                any(_related(left, right) for left in path_values for right in governance.refs(raw.get("paths")))
                or set(interface_values).intersection(governance.refs(raw.get("interfaces")))
                or set(governance_values).intersection(governance.refs(raw.get("governance")))
            ):
                overlaps.append(str(raw.get("unit")))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    value: dict[str, Any] = {
        "version": 1,
        "unit": unit,
        "owner": owner,
        "branch": branch,
        "worktree": worktree,
        "task": task,
    }
    if scope:
        value["scope"] = scope
    if interface_values:
        value["interfaces"] = interface_values
    if path_values:
        value["paths"] = path_values
    if governance_values:
        value["governance"] = governance_values
    if domain_values:
        value["domains"] = domain_values
        value["governing_digest"] = digest
    tip = git.resolve(repo, f"refs/heads/{branch}") if branch else None
    ground = git.resolve(repo, f"refs/heads/{target}") if target else None
    if tip:
        value["tip"] = tip
    if ground:
        value["ground"] = ground
    if target:
        value["integration_target"] = target
    value["created"] = _utc(now)
    value["renewed"] = _utc(now)
    value["expires"] = _utc(now + timedelta(seconds=_duration(duration)))
    ensure_runtime(repo)
    dump_yaml(path, value)
    if overlaps:
        return [f"LEASE: {unit} created — intersects {' '.join(overlaps)}; expires {value['expires']}"]
    return [f"LEASE: {unit} created — no live unit intersects; expires {value['expires']}"]


def renew_lease(repo: Path, unit: str, duration: str = "2h") -> list[str]:
    value = _lease(repo, unit)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    branch = str(value.get("branch") or "")
    value["renewed"] = _utc(now)
    value["expires"] = _utc(now + timedelta(seconds=_duration(duration)))
    if branch:
        value["tip"] = git.resolve(repo, f"refs/heads/{branch}") or "unknown"
    dump_yaml(_lease_path(repo, unit), value)
    return [f"LEASE: {unit} renewed — expires {value['expires']}"]


def lease_fresh(repo: Path, unit: str) -> list[str]:
    value = _lease(repo, unit)
    ground = value.get("ground")
    target = value.get("integration_target") or config.resolve(repo).integration_branch
    if not ground or not target or not git.resolve(repo, str(ground)):
        return [f"FRESH: {unit} — no recorded ground to compare; re-lease to record one"]
    landed = git.changed_paths(repo, str(ground), f"refs/heads/{target}")
    if not landed:
        return [f"FRESH: {unit} — nothing landed since the recorded ground"]
    hit: str | None = None
    for candidate in landed:
        if any(_related(candidate, claim) for claim in governance.refs(value.get("paths"))):
            hit = candidate
            break
    if not hit:
        diff = git.run(["diff", str(ground), f"refs/heads/{target}", "--"], cwd=repo, check=False).stdout
        for interface in governance.refs(value.get("interfaces")):
            if interface in diff:
                hit = f"interface:{interface}"
                break
    domain_values = governance.refs(value.get("domains"))
    if not hit and (governance.refs(value.get("governance")) or domain_values):
        if any(path in governance.GOVERNANCE_FILES for path in landed):
            hit = "governance"
    if not hit and domain_values:
        material = governance.material_changes(repo, str(ground), f"refs/heads/{target}", domain_values)
        if material:
            hit = material[0].removeprefix("MATERIAL-CHANGED: ")
    if hit:
        raise Blocked(
            f"STALE: {unit} — intersecting landing touched {hit}; re-lease against the new ground or release",
            code="stale_lease",
        )
    return [f"FRESH: {unit} — no intersecting landing since the recorded ground"]


def release_lease(repo: Path, unit: str) -> list[str]:
    path = _lease_path(repo, unit)
    if not path.is_file():
        raise InvariantError(f"Invariant: no lease for '{unit}'")
    path.unlink()
    return [f"released {unit}"]


def list_leases(repo: Path, *, scope: str | None = None, domain: str | None = None) -> list[str]:
    directory = runtime_root(repo) / "leases"
    files = sorted(directory.glob("*.yml")) if directory.is_dir() else []
    now = datetime.now(timezone.utc)
    output: list[str] = []
    for path in files:
        raw = load_yaml(path)
        if not isinstance(raw, dict):
            continue
        if scope and raw.get("scope") != scope:
            continue
        if domain and domain not in governance.refs(raw.get("domains")):
            continue
        expires = str(raw.get("expires") or "")
        try:
            status = "expired" if _parse_utc(expires) < now else "live"
        except ValueError:
            status = "live"
        output.append(
            f"LEASE: {raw.get('unit')} {raw.get('scope') or '<no scope>'} — expires {expires} ({status})"
        )
    return output or ["no leases"]


@dataclass(frozen=True)
class ReapResult:
    lines: list[str]
    reaped: int
    renewed: int


def reap_leases(repo: Path, *, apply: bool = False) -> ReapResult:
    directory = runtime_root(repo) / "leases"
    files = sorted(directory.glob("*.yml")) if directory.is_dir() else []
    now = datetime.now(timezone.utc)
    output: list[str] = []
    reaped = renewed = 0
    for path in files:
        value = load_yaml(path)
        if not isinstance(value, dict):
            continue
        unit = str(value.get("unit"))
        branch = str(value.get("branch") or "")
        worktree = str(value.get("worktree") or "")
        tip = str(value.get("tip") or "")
        target = str(value.get("integration_target") or config.resolve(repo).integration_branch)
        exists = bool(branch and git.branch_exists(repo, branch))
        try:
            expired = _parse_utc(str(value.get("expires") or "")) < now
        except ValueError:
            expired = False
        dead = ""
        if exists and target and branch != target and git.is_ancestor(repo, branch, target):
            dead = f"branch merged into {target}"
        elif not exists and worktree and not Path(worktree).is_dir():
            dead = "branch and worktree gone"
        elif not exists and expired:
            dead = "branch missing, lease expired"
        if dead:
            output.append(f"DEAD: {unit} ({dead})")
            if apply:
                path.unlink()
                reaped += 1
        elif expired:
            current_tip = git.resolve(repo, f"refs/heads/{branch}") if exists else None
            if current_tip and tip and current_tip != tip:
                output.append(f"RENEW: {unit} — tip advanced since grant; the worker is alive")
                if apply:
                    renew_lease(repo, unit)
                    renewed += 1
            else:
                output.append(
                    f"QUIESCENT: {unit} — expired, tip unmoved; reap ends the reservation, the work remains"
                )
                if apply:
                    path.unlink()
                    reaped += 1
        else:
            output.append(f"LIVE: {unit}")
    if not files:
        output.append("no leases")
    if apply:
        output.append(f"reaped {reaped} lease(s), renewed {renewed}")
    return ReapResult(output, reaped, renewed)


def runtime_status(repo: Path) -> list[str]:
    runtime = runtime_root(repo)
    output = [f"RUNTIME: {runtime}"]
    if not runtime.is_dir():
        return [*output, "STATUS: empty"]
    briefs = (
        sorted((runtime / "briefs").glob("*.yml"))
        if (runtime / "briefs").is_dir()
        else []
    )
    output.extend(f"ACTIVE-TASK: {path.stem}" for path in briefs)
    if not briefs:
        output.append("ACTIVE-TASKS: none")
    history = runtime / "history" / "tasks"
    completions = sorted(history.glob("*/*/summary.yml")) if history.is_dir() else []
    output.extend(
        f"COMPLETED-TASK: {path.parents[1].name}@{path.parent.name}"
        for path in completions
    )
    if not completions:
        output.append("COMPLETED-TASKS: none")
    verifications = runtime / "verifications"
    verification_receipts = (
        sorted(verifications.glob("*.yml")) if verifications.is_dir() else []
    )
    output.append(f"VERIFICATION-RECEIPTS: {len(verification_receipts)}")
    plans = (
        sorted((runtime / "plans").glob("*.yml"))
        if (runtime / "plans").is_dir()
        else []
    )
    for path in plans:
        output.append(f"PLAN: {path.stem}")
        output.extend(f"  {line}" for line in plan_status(repo, path.stem))
    if not plans:
        output.append("PLANS: none")
    output.extend(list_leases(repo))
    leases = (
        sorted((runtime / "leases").glob("*.yml"))
        if (runtime / "leases").is_dir()
        else []
    )
    for path in leases:
        try:
            raw = load_yaml(path)
            output.extend(lease_fresh(repo, str(raw.get("unit"))))
        except InvariantError as exc:
            output.append(exc.message)
    return output


def clean_runtime(repo: Path, *, apply: bool = False) -> list[str]:
    if apply:
        ensure_runtime(repo)
    runtime = runtime_root(repo)
    if not runtime.is_dir():
        return ["CLEAN: nothing to do"]
    result = reap_leases(repo, apply=apply)
    output = list(result.lines)
    plans = (
        sorted((runtime / "plans").glob("*.yml"))
        if (runtime / "plans").is_dir()
        else []
    )
    for path in plans:
        status = plan_status(repo, path.stem)
        complete = all(" landed " in f" {line} " for line in status[1:] if line.strip())
        if complete:
            if apply:
                path.unlink()
                output.append(f"CLEANED: completed plan {path.stem}")
            else:
                output.append(f"CLEANABLE: completed plan {path.stem}")
    history = runtime / "history" / "tasks"
    completions = sorted(history.glob("*/*")) if history.is_dir() else []
    for path in completions:
        if not path.is_dir():
            continue
        label = f"{path.parent.name}@{path.name}"
        if apply:
            shutil.rmtree(path)
            output.append(f"CLEANED: completed task {label}")
        else:
            output.append(f"CLEANABLE: completed task {label}")
    verifications = runtime / "verifications"
    verification_files = sorted(verifications.iterdir()) if verifications.is_dir() else []
    if verification_files:
        if apply:
            shutil.rmtree(verifications)
            output.append(f"CLEANED: {len(verification_files)} verification cache file(s)")
        else:
            output.append(f"CLEANABLE: {len(verification_files)} verification cache file(s)")
    if apply:
        for directory in sorted((item for item in runtime.rglob("*") if item.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        payload = (
            [item for item in runtime.iterdir() if item.name != ".gitignore"]
            if runtime.exists()
            else []
        )
        if not payload:
            (runtime / ".gitignore").unlink(missing_ok=True)
            try:
                runtime.rmdir()
            except OSError:
                pass
    return output
