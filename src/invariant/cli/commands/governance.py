from __future__ import annotations

import argparse
from pathlib import Path

from invariant.errors import Blocked, InvariantError
from invariant.lifecycle import tasks
from invariant.mechanics import audit, config, git, receipts
from invariant.mechanics.documents import dump_yaml, load_yaml


DEFAULT_GOAL = "Reconcile the repository's durable governance with a causal audit."
TASK_ID_HELP = "caller-chosen ID for this governance pass"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "governance",
        help="Run an audit, adoption, and verification pass as one resumable session",
    )
    commands = parser.add_subparsers(dest="governance_command", required=True)

    begin = commands.add_parser("begin", help="Open the managed worktree before creating an audit")
    begin.add_argument("task_id", help=TASK_ID_HELP)
    begin.add_argument("--goal", default=DEFAULT_GOAL)
    begin.set_defaults(_handler=_begin, _command="governance.begin")

    save = commands.add_parser("audit-save", help="Save the full audit inside the managed session")
    save.add_argument("task_id", help=TASK_ID_HELP)
    save.add_argument("--input", type=Path, required=True)
    save.set_defaults(_handler=_audit_save, _command="governance.audit-save")

    adopt = commands.add_parser("adopt", help="Select ready audit findings for governance adoption")
    adopt.add_argument("task_id", help=TASK_ID_HELP)
    selection = adopt.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all-ready", action="store_true")
    selection.add_argument("--finding", action="append")
    adopt.set_defaults(_handler=_adopt, _command="governance.adopt")

    defer = commands.add_parser(
        "defer", help="Land the saved audit without adopting durable governance"
    )
    defer.add_argument("task_id", help=TASK_ID_HELP)
    defer.set_defaults(_handler=_defer, _command="governance.defer")

    status = commands.add_parser("status", help="Show the governance phase and managed task state")
    status.add_argument("task_id", help=TASK_ID_HELP)
    status.set_defaults(_handler=_status, _command="governance.status")


def _session(repo: Path, task: str) -> tuple[dict[str, object], dict[str, object]]:
    receipt = receipts.load(repo, task)
    session = (
        receipt.get("governance_run")
        if isinstance(receipt.get("governance_run"), dict)
        else None
    )
    if session is None:
        raise Blocked(f"Invariant: task '{task}' is not a governance pass")
    return receipt, session


def _authority(repo: Path, receipt: dict[str, object]) -> str:
    proposed = config.resolve(repo)
    ground = str(receipt.get("integration_head") or "")
    target = str(receipt.get("integration_target") or "")
    if proposed.authority != "agent" or ground == "unborn":
        return proposed.authority
    accepted = config.resolve_at(repo, ground, target)
    return "agent" if accepted.authority == "agent" else "human"


def _candidate_repo(repo: Path, receipt: dict[str, object]) -> Path:
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    stage = str(lifecycle.get("stage") or "")
    if stage == "implementing-unborn":
        return repo
    worktree = Path(str(lifecycle.get("worktree") or ""))
    branch = str(lifecycle.get("branch") or "")
    if not worktree.is_dir() or git.current_branch(worktree) != branch:
        raise Blocked(
            f"Invariant: governance task worktree for '{branch}' is unavailable",
            code="missing_task_worktree",
        )
    return worktree


def _begin(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    lines = tasks.begin(
        repo,
        args.task_id,
        goal=args.goal,
        boundary="unresolved",
        paths=[],
        interfaces=[],
        domains=[],
        adapter_overrides={"intent_brief": False},
    )
    receipt = receipts.load(repo, args.task_id)
    receipt["governance_run"] = {"phase": "audit"}
    receipts.save(repo, args.task_id, receipt)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    if lifecycle.get("stage") in {"implementing", "implementing-unborn"}:
        candidate = _candidate_repo(repo, receipt)
        lines.extend(["GOVERNANCE-PHASE: audit", *audit.full(candidate, _authority(repo, receipt))])
    else:
        lines.append("NEXT: continue the lifecycle, then rerun governance status")
    return lines


def _audit_save(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    receipt, session = _session(repo, args.task_id)
    if session.get("phase") != "audit":
        raise Blocked(
            f"Invariant: governance audit is already in phase '{session.get('phase')}'"
        )
    candidate = _candidate_repo(repo, receipt)
    authority = _authority(repo, receipt)
    lines = audit.save(
        candidate,
        "audit",
        mode="full",
        source=args.input,
        paths=[],
        domains=[],
        authority=authority,
    )
    audit_id = next(line.removeprefix("AUDIT: ") for line in lines if line.startswith("AUDIT: "))
    raw = load_yaml(candidate / ".invariant" / "audits" / f"{audit_id}.yml")
    findings = raw.get("findings", []) if isinstance(raw, dict) else []
    ready = [
        str(finding.get("id"))
        for finding in findings
        if isinstance(finding, dict) and finding.get("disposition") == "adoptable"
    ]
    session["audit"] = audit_id
    if authority == "agent":
        session["phase"] = "adopt"
        session["selected_findings"] = ready
        lines.extend(
            [
                "GOVERNANCE-PHASE: adopt",
                f"SELECTED-FINDINGS: {', '.join(ready) or 'none ready'}",
            ]
        )
    else:
        session["phase"] = "decision"
        lines.append("GOVERNANCE-PHASE: decision")
    receipt["governance_run"] = session
    receipts.save(repo, args.task_id, receipt)
    return lines


def _adopt(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    receipt, session = _session(repo, args.task_id)
    if session.get("phase") not in {"decision", "adopt"}:
        raise Blocked(f"Invariant: adoption is unavailable in phase '{session.get('phase')}'")
    audit_id = str(session.get("audit") or "")
    candidate = _candidate_repo(repo, receipt)
    raw = load_yaml(candidate / ".invariant" / "audits" / f"{audit_id}.yml")
    findings = raw.get("findings", []) if isinstance(raw, dict) else []
    available = {
        str(finding.get("id")): str(finding.get("disposition"))
        for finding in findings
        if isinstance(finding, dict) and finding.get("id")
    }
    selected = (
        sorted(identifier for identifier, disposition in available.items() if disposition == "adoptable")
        if args.all_ready
        else sorted(set(args.finding or []))
    )
    missing = [identifier for identifier in selected if identifier not in available]
    if missing:
        raise InvariantError(f"Invariant: audit has no finding '{missing[0]}'")
    session["phase"] = "adopt"
    session["selected_findings"] = selected
    receipt["governance_run"] = session
    receipts.save(repo, args.task_id, receipt)
    return [
        f"GOVERNANCE-PHASE: adopt",
        f"AUDIT: {audit_id}",
        f"SELECTED-FINDINGS: {', '.join(selected) or 'none'}",
        "NEXT: record and commit the selected durable meaning in the task worktree, then run task finish",
    ]


def _status(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    receipt, session = _session(repo, args.task_id)
    lines = [
        f"GOVERNANCE-PHASE: {session.get('phase')}",
        f"AUDIT: {session.get('audit') or 'not saved'}",
    ]
    selected = session.get("selected_findings")
    if isinstance(selected, list):
        lines.append(f"SELECTED-FINDINGS: {', '.join(str(item) for item in selected) or 'none'}")
    lines.extend(tasks.status(repo, args.task_id))
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    if session.get("phase") == "audit" and lifecycle.get("stage") in {
        "implementing",
        "implementing-unborn",
    }:
        lines.extend(audit.full(_candidate_repo(repo, receipt), _authority(repo, receipt)))
    return lines


def _defer(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    receipt, session = _session(repo, args.task_id)
    if session.get("phase") == "deferred":
        return ["GOVERNANCE-PHASE: deferred", *tasks.status(repo, args.task_id)]
    if session.get("phase") not in {"decision", "adopt"}:
        raise Blocked(f"Invariant: deferral is unavailable in phase '{session.get('phase')}'")
    audit_id = str(session.get("audit") or "")
    audit_path = f".invariant/audits/{audit_id}.yml"
    candidate = _candidate_repo(repo, receipt)
    if not (candidate / audit_path).is_file():
        raise Blocked(f"Invariant: saved audit '{audit_id}' is absent")
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    branch = str(lifecycle.get("branch") or "")
    working = git.changed_paths(candidate)
    if working:
        if set(working) != {audit_path}:
            raise Blocked(
                "Invariant: deferral can commit only the saved audit; preserve or commit other work first",
                lines=[f"CHANGED: {path}" for path in working],
            )
        git.run(["add", "--", audit_path], cwd=candidate)
        git.run(["commit", "-q", "-m", f"Record deferred governance audit {audit_id}"], cwd=candidate)
    base = str(receipt.get("integration_head") or "")
    branch_ref = git.resolve(candidate, f"refs/heads/{branch}") if branch else None
    candidate_paths = git.changed_paths(candidate, base, branch_ref) if branch_ref and base != "unborn" else [audit_path]
    if set(candidate_paths) != {audit_path}:
        raise Blocked(
            "Invariant: deferral candidate contains changes beyond the saved audit",
            lines=[f"CANDIDATE-PATH: {path}" for path in candidate_paths],
        )
    assessment = {
        "version": 1,
        "goal_digest": str(receipt.get("goal_digest") or ""),
        "paths": [audit_path],
        "interfaces": [],
        "domains": [],
        "boundary": {"disposition": "no-record"},
        "governance": [],
        "architecture_reviews": [],
        "checks": [],
        "allow_open": False,
    }
    local = receipts.task_root(repo, args.task_id)
    assessment_path = local / "deferred-audit-assessment.yml"
    dump_yaml(assessment_path, assessment)
    session["phase"] = "deferred"
    receipt["governance_run"] = session
    receipts.save(repo, args.task_id, receipt)
    return [
        "GOVERNANCE-PHASE: deferred",
        *tasks.finish(
            repo,
            args.task_id,
            assessment_path=str(assessment_path),
            subject=f"Record deferred governance audit {audit_id}",
        ),
    ]
