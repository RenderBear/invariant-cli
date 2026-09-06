from __future__ import annotations

import argparse

from invariant.lifecycle import tasks
from invariant.mechanics import config, git, receipts, state
from invariant.mechanics.documents import load_yaml


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "status", help="Show repository health, active tasks, and the next useful command"
    )
    parser.add_argument(
        "task_id",
        nargs="?",
        help="optional caller-chosen ID of one active managed repository change",
    )
    parser.set_defaults(_handler=_status, _command="status")


def _status(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    if args.task_id:
        return tasks.status(repo, args.task_id)
    resolved = config.resolve(repo)
    validation = state.validate(repo)
    valid = validation[-1] in {
        "Invariant state valid",
        "no Invariant state — nothing to validate",
    }
    lines = [
        f"REPOSITORY: {repo}",
        f"BRANCH: {git.current_branch(repo) or 'detached'}",
        f"INTEGRATION: {resolved.integration_branch}",
        f"AUTHORITY: {resolved.authority}",
        f"EXECUTION: {resolved.execution}",
        f"STATE: {'valid' if valid else 'invalid'}",
    ]
    root = receipts.receipt_root(repo)
    active = sorted(root.glob("*.yml")) if root.is_dir() else []
    for path in active:
        raw = load_yaml(path)
        if not isinstance(raw, dict):
            continue
        lifecycle = raw.get("lifecycle") if isinstance(raw.get("lifecycle"), dict) else {}
        lines.append(f"TASK: {raw.get('task')} ({lifecycle.get('stage') or 'briefed'})")
    lines.append(f"ACTIVE-TASKS: {len(active)}")
    if not valid:
        lines.append("NEXT: invariant state validate")
    elif active:
        lines.append("NEXT: invariant status <task-id>")
    else:
        lines.append("NEXT: invariant task begin <task-id> --goal <text>")
    return lines
