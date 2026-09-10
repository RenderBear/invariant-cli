"""Compatibility adapters for the pre-package shell command surfaces.

The adapters deliberately contain argument translation only.  Semantics,
mechanics, and lifecycle live in the normal package modules, so the old skill
script paths cannot become a second implementation.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from invariant.errors import Blocked, InvariantError, UsageError
from invariant.mechanics import audit, config, coordinate, git, governance, landing, receipts, state


Parsed = tuple[list[str], dict[str, list[str]], set[str]]


def _parse(
    argv: list[str],
    *,
    one: Iterable[str] = (),
    many: Iterable[str] = (),
    flags: Iterable[str] = (),
) -> Parsed:
    """Parse the deliberately small legacy option grammar.

    ``one`` options consume one value and may repeat. ``many`` options consume
    every following non-option value and may repeat. Everything else is a
    positional argument. Unknown options are rejected.
    """

    one_set, many_set, flag_set = set(one), set(many), set(flags)
    values: dict[str, list[str]] = defaultdict(list)
    enabled: set[str] = set()
    positional: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in flag_set:
            enabled.add(token)
            index += 1
        elif token in one_set:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise UsageError(f"Invariant: {token} requires a value")
            values[token].append(argv[index + 1])
            index += 2
        elif token in many_set:
            index += 1
            start = index
            while index < len(argv) and not argv[index].startswith("--"):
                values[token].append(argv[index])
                index += 1
            if index == start:
                raise UsageError(f"Invariant: {token} requires at least one value")
        elif token.startswith("--"):
            raise UsageError(f"Invariant: unsupported option '{token}'")
        else:
            positional.append(token)
            index += 1
    return positional, values, enabled


def _exact(positionals: list[str], count: int, usage: str) -> None:
    if len(positionals) != count:
        raise UsageError(usage)


def _config(_: list[str]) -> list[str]:
    resolved = config.resolve(git.root())
    # Preserve the legacy resolver's stable six-line contract. The public CLI
    # exposes the schema version, remote policy, and lifecycle switches as well.
    return [
        f"authority: {resolved.authority}",
        f"execution: {resolved.execution}",
        f"integration_branch: {resolved.integration_branch}",
        f"source: {resolved.source}",
        f"integration_branch_resolved: {resolved.integration_branch}",
        f"branch_source: {resolved.branch_source}",
        *(["integration_branch_unborn: true"] if resolved.unborn else []),
    ]


def _state(argv: list[str]) -> list[str]:
    landing_mode = False
    if argv and argv[0] in {"--landing", "--audit"}:
        landing_mode = argv.pop(0) == "--landing"
    lines = state.validate(git.root(), landing=landing_mode, named=argv)
    if lines[-1].endswith("Invariant state violation(s)"):
        raise Blocked(lines[-1], code="invalid_state", lines=lines[:-1])
    return lines


def _scope(argv: list[str]) -> tuple[str | None, bool, bool, list[str], list[str], list[str]]:
    positional, values, flags = _parse(
        argv,
        one=("--history", "--domain", "--interface"),
        many=("--paths",),
        flags=("--root",),
    )
    if len(positional) > 1:
        raise UsageError("Invariant: reach accepts at most one base ref")
    history_value = values.get("--history", [])
    if positional and history_value:
        raise UsageError("Invariant: choose a base ref or --history, not both")
    base = history_value[-1] if history_value else (positional[0] if positional else None)
    return (
        base,
        bool(history_value),
        "--root" in flags,
        values.get("--paths", []),
        values.get("--domain", []),
        values.get("--interface", []),
    )


def _brief(argv: list[str]) -> list[str]:
    if not argv:
        raise UsageError("usage: brief-support.sh <command> ...")
    repo, command, rest = git.root(), argv[0], argv[1:]
    if command == "map":
        _exact(rest, 0, "usage: brief-support.sh map")
        return governance.context_map(repo)
    if command == "rows":
        return governance.display_rows(repo, rest)
    if command == "digest":
        positional, values, _ = _parse(rest, one=("--at",))
        at = values.get("--at", [None])[-1]
        return [f"DIGEST: {governance.digest(repo, positional, at)}"]
    if command == "check-digest":
        if not rest:
            raise UsageError("usage: brief-support.sh check-digest <digest> [domain ...]")
        expected, selected = rest[0], rest[1:]
        actual = governance.digest(repo, selected)
        if actual != expected:
            raise Blocked(f"STALE: expected {expected} actual {actual}")
        return [f"DIGEST: fresh {actual}"]
    if command in {"reach", "verifiers"}:
        base, history, root_mode, paths, domains, interfaces = _scope(rest)
        function = governance.reach if command == "reach" else governance.verifiers
        return function(
            repo,
            base=base,
            history=history,
            root_mode=root_mode,
            paths=paths or None,
            domains_selected=domains,
            interfaces=interfaces,
        )
    if command == "material-changes":
        if len(rest) < 2:
            raise UsageError("usage: brief-support.sh material-changes <base> <tip> [domain ...]")
        return governance.material_changes(repo, rest[0], rest[1], rest[2:])
    if command == "message":
        if not rest:
            raise UsageError("usage: brief-support.sh message <subject> ...")
        subject = rest[0]
        positional, values, _ = _parse(
            rest[1:], one=("--unit", "--scope", "--domain", "--plan")
        )
        _exact(positional, 0, "usage: brief-support.sh message <subject> ...")
        plan = values.get("--plan", [None])[-1]
        return governance.commit_message(
            repo,
            subject,
            values.get("--unit", []),
            values.get("--scope", []),
            values.get("--domain", []),
            plan,
        ).rstrip("\n").splitlines()
    if command == "trailer":
        _exact(rest, 1, "usage: brief-support.sh trailer <commit>")
        return governance.validate_trailer(repo, rest[0])
    raise UsageError(f"Invariant: unknown brief command '{command}'")


def _audit(argv: list[str]) -> list[str]:
    if not argv:
        raise UsageError("usage: audit-support.sh <scope|full|fresh> ...")
    repo, command, rest = git.root(), argv[0], argv[1:]
    if command == "scope":
        positional, values, _ = _parse(rest, many=("--paths",))
        _exact(positional, 0, "usage: audit-support.sh scope --paths <path> ...")
        if not values.get("--paths"):
            raise UsageError("Invariant: scoped audit requires --paths")
        return audit.frame(repo, "scope", values["--paths"])
    if command == "full":
        positional, _, flags = _parse(rest, flags=("--human", "--agent"))
        _exact(positional, 0, "usage: audit-support.sh full --human|--agent")
        if len(flags) != 1:
            raise UsageError("Invariant: full audit requires exactly one authority mode")
        return audit.full(repo, "agent" if "--agent" in flags else "human")
    if command == "fresh":
        if len(rest) not in {1, 2}:
            raise UsageError("usage: audit-support.sh fresh <audit> [head]")
        return audit.fresh(repo, rest[0], rest[1] if len(rest) == 2 else "HEAD")
    raise UsageError(f"Invariant: unknown audit command '{command}'")


def _session(argv: list[str]) -> list[str]:
    if len(argv) < 2:
        raise UsageError("usage: session-brief.sh <open|check|invalidate> <task> ...")
    repo, command, task, rest = git.root(), argv[0], argv[1], argv[2:]
    if command == "invalidate":
        _exact(rest, 0, "usage: session-brief.sh invalidate <task>")
        return receipts.invalidate(repo, task)
    if command == "open":
        positional, values, _ = _parse(
            rest,
            one=("--goal", "--posture", "--boundary", "--path", "--interface", "--domain"),
        )
        _exact(positional, 0, "usage: session-brief.sh open <task> ...")
        for required in ("--goal", "--posture", "--boundary"):
            if len(values.get(required, [])) != 1:
                raise UsageError(f"Invariant: open requires exactly one {required}")
        _, lines = receipts.open_receipt(
            repo,
            task,
            goal=values["--goal"][0],
            posture=values["--posture"][0],
            boundary=values["--boundary"][0],
            paths=values.get("--path", []),
            interfaces=values.get("--interface", []),
            domains=values.get("--domain", []),
        )
        return lines
    if command == "check":
        positional, values, flags = _parse(
            rest,
            one=("--goal", "--goal-digest", "--path", "--interface", "--domain"),
            flags=("--compatible-goal",),
        )
        _exact(positional, 0, "usage: session-brief.sh check <task> ...")
        goal = values.get("--goal", [None])[-1]
        goal_digest = values.get("--goal-digest", [None])[-1]
        _, lines = receipts.check_receipt(
            repo,
            task,
            goal=goal,
            goal_digest=goal_digest,
            compatible_goal="--compatible-goal" in flags,
            paths=values.get("--path") or None,
            interfaces=values.get("--interface") or None,
            domains=values.get("--domain") or None,
        )
        return lines
    raise UsageError(f"Invariant: unknown session command '{command}'")


def _runtime(argv: list[str]) -> list[str]:
    if not argv:
        raise UsageError("usage: runtime-support.sh <root|ensure|status|clean>")
    repo, command, rest = git.root(), argv[0], argv[1:]
    if command == "root":
        _exact(rest, 0, "usage: runtime-support.sh root")
        return [str(coordinate.runtime_root(repo))]
    if command == "ensure":
        _exact(rest, 0, "usage: runtime-support.sh ensure")
        return [str(coordinate.ensure_runtime(repo))]
    if command == "status":
        _exact(rest, 0, "usage: runtime-support.sh status")
        return coordinate.runtime_status(repo)
    if command == "clean":
        positional, _, flags = _parse(rest, flags=("--apply",))
        _exact(positional, 0, "usage: runtime-support.sh clean [--apply]")
        return coordinate.clean_runtime(repo, apply="--apply" in flags)
    raise UsageError(f"Invariant: unknown runtime command '{command}'")


def _workboard(argv: list[str]) -> list[str]:
    if len(argv) != 2 or argv[0] != "validate":
        raise UsageError("usage: workboard-support.sh validate <plan>")
    return coordinate.validate_plan(git.root(), argv[1])


def _workboard_status(argv: list[str]) -> list[str]:
    positional, _, flags = _parse(argv, flags=("--pinned",))
    if len(positional) > 1:
        raise UsageError("usage: workboard-status.sh [plan [--pinned]]")
    return coordinate.plan_status(
        git.root(), positional[0] if positional else None, pinned="--pinned" in flags
    )


def _lease(argv: list[str]) -> list[str]:
    if not argv:
        raise UsageError("usage: lease-support.sh <create|renew|release|list|fresh|reap> ...")
    repo, command, rest = git.root(), argv[0], argv[1:]
    if command == "create":
        if not rest:
            raise UsageError("usage: lease-support.sh create <unit> ...")
        unit = rest[0]
        positional, values, _ = _parse(
            rest[1:],
            one=(
                "--scope", "--branch", "--worktree", "--task", "--owner",
                "--integration-target", "--duration", "--digest",
            ),
            many=("--paths", "--interfaces", "--governance", "--domains"),
        )
        _exact(positional, 0, "usage: lease-support.sh create <unit> ...")
        return coordinate.create_lease(
            repo,
            unit,
            scope=values.get("--scope", [None])[-1],
            paths=values.get("--paths", []),
            interfaces=values.get("--interfaces", []),
            governance_claims=values.get("--governance", []),
            domains=values.get("--domains", []),
            digest=values.get("--digest", [None])[-1],
            branch=values.get("--branch", [None])[-1],
            worktree=values.get("--worktree", [None])[-1],
            task=values.get("--task", [None])[-1],
            owner=values.get("--owner", [None])[-1],
            integration_target=values.get("--integration-target", [None])[-1],
            duration=values.get("--duration", ["2h"])[-1],
        )
    if command == "renew":
        positional, values, _ = _parse(rest, one=("--duration",))
        _exact(positional, 1, "usage: lease-support.sh renew <unit> [--duration <time>]")
        return coordinate.renew_lease(repo, positional[0], values.get("--duration", ["2h"])[-1])
    if command == "release":
        _exact(rest, 1, "usage: lease-support.sh release <unit>")
        return coordinate.release_lease(repo, rest[0])
    if command == "list":
        positional, values, _ = _parse(rest, one=("--scope", "--domain"))
        _exact(positional, 0, "usage: lease-support.sh list [filters]")
        return coordinate.list_leases(
            repo,
            scope=values.get("--scope", [None])[-1],
            domain=values.get("--domain", [None])[-1],
        )
    if command == "fresh":
        _exact(rest, 1, "usage: lease-support.sh fresh <unit>")
        return coordinate.lease_fresh(repo, rest[0])
    if command == "reap":
        positional, _, flags = _parse(rest, flags=("--apply",))
        _exact(positional, 0, "usage: lease-support.sh reap [--apply]")
        return coordinate.reap_leases(repo, apply="--apply" in flags).lines
    raise UsageError(f"Invariant: unknown lease command '{command}'")


def _land(argv: list[str]) -> list[str]:
    if len(argv) < 2:
        raise UsageError("usage: land-support.sh <direct|staged|merge> ...")
    mode = argv[0]
    if mode == "merge":
        if len(argv) < 3:
            raise UsageError("usage: land-support.sh merge <branch> <subject> ...")
        branch, subject, rest = argv[1], argv[2], argv[3:]
    elif mode in {"direct", "staged"}:
        branch, subject, rest = None, argv[1], argv[2:]
    else:
        raise UsageError(f"Invariant: invalid landing mode '{mode}'")
    positional, values, flags = _parse(
        rest,
        one=(
            "--unit", "--scope", "--domain", "--interface", "--governance",
            "--reviewed", "--boundary-review", "--target", "--plan", "--check",
        ),
        many=("--paths",),
        flags=("--allow-open",),
    )
    _exact(positional, 0, "usage: land-support.sh <mode> ...")
    boundary_values = values.get("--boundary-review", [])
    if len(boundary_values) != 1:
        raise UsageError("Invariant: landing requires exactly one --boundary-review disposition")
    request = landing.LandRequest(
        mode=mode,
        merge_branch=branch,
        subject=subject,
        units=tuple(values.get("--unit", [])),
        scopes=tuple(values.get("--scope", [])),
        boundary=boundary_values[0],
        paths=tuple(values.get("--paths", [])),
        domains=tuple(values.get("--domain", [])),
        interfaces=tuple(values.get("--interface", [])),
        governance_refs=tuple(values.get("--governance", [])),
        reviewed=tuple(values.get("--reviewed", [])),
        checks=tuple(values.get("--check", [])),
        target=values.get("--target", [None])[-1],
        plan=values.get("--plan", [None])[-1],
        allow_open="--allow-open" in flags,
    )
    return landing.verify_and_land(git.root(), request)


def _direct_edit(argv: list[str]) -> list[str]:
    if not argv:
        raise UsageError("usage: direct-edit.sh <subject> --unit <id> --no-record ...")
    subject = argv[0]
    positional, values, flags = _parse(
        argv[1:], one=("--unit", "--target", "--check"), flags=("--no-record",)
    )
    _exact(positional, 0, "usage: direct-edit.sh <subject> ...")
    if len(values.get("--unit", [])) != 1:
        raise UsageError("Invariant: direct edit requires exactly one --unit")
    if "--no-record" not in flags:
        raise UsageError("Invariant: direct edit requires exactly one explicit --no-record disposition")
    return landing.direct_edit(
        git.root(),
        subject,
        values["--unit"][0],
        values.get("--check", []),
        values.get("--target", [None])[-1],
    )


ADAPTERS: dict[str, Callable[[list[str]], list[str]]] = {
    "audit": _audit,
    "brief": _brief,
    "config": _config,
    "direct-edit": _direct_edit,
    "land": _land,
    "lease": _lease,
    "runtime": _runtime,
    "session": _session,
    "state": _state,
    "workboard": _workboard,
    "workboard-status": _workboard_status,
}


def run(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if not arguments or arguments[0] not in ADAPTERS:
            raise UsageError("Invariant: missing compatibility adapter")
        lines = ADAPTERS[arguments[0]](arguments[1:])
        if lines:
            print("\n".join(lines))
        return 0
    except InvariantError as exc:
        if exc.lines:
            print("\n".join(exc.lines))
        # The historical helpers treated policy blocks as report rows on
        # stdout, while malformed invocation and mechanical failures used
        # stderr. Keep that contract only at this compatibility boundary.
        stream = sys.stdout if exc.exit_code == 1 else sys.stderr
        print(exc.message, file=stream)
        return exc.exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
