from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import yaml

from invariant.cli.output import CommandResult
from invariant.errors import Blocked, InvariantError
from invariant.lifecycle import tasks
from invariant.mechanics import audit, config, git, receipts, state
from invariant.mechanics.documents import dump_yaml, load_yaml
from invariant.semantics.adoption import AdoptionManifest, example, schema


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

    project = commands.add_parser(
        "project", help="Materialize selected findings through an adoption manifest"
    )
    project.add_argument("task_id", help=TASK_ID_HELP)
    project.add_argument(
        "--input",
        type=Path,
        help="edited adoption manifest; omit to project records authored in the audit",
    )
    project.set_defaults(_handler=_project, _command="governance.project")

    coverage = commands.add_parser(
        "coverage", help="Report how every selected finding is dispositioned"
    )
    coverage.add_argument("task_id", help=TASK_ID_HELP)
    coverage.set_defaults(_handler=_coverage, _command="governance.coverage")

    projection = commands.add_parser(
        "projection", help="Inspect the adoption projection protocol"
    )
    projections = projection.add_subparsers(dest="projection_command", required=True)
    projection_schema = projections.add_parser("schema")
    projection_schema.set_defaults(
        _handler=_projection_schema, _command="governance.projection.schema"
    )
    projection_example = projections.add_parser("example")
    projection_example.set_defaults(
        _handler=_projection_example, _command="governance.projection.example"
    )

    defer = commands.add_parser(
        "defer", help="Land the saved audit without adopting durable governance"
    )
    defer.add_argument("task_id", help=TASK_ID_HELP)
    defer.set_defaults(_handler=_defer, _command="governance.defer")

    status = commands.add_parser("status", help="Show the governance phase and managed task state")
    status.add_argument("task_id", help=TASK_ID_HELP)
    status.set_defaults(_handler=_status, _command="governance.status")


def _session(
    repo: Path,
    task: str,
    *,
    allow_completed: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        receipt = receipts.load(repo, task)
    except Blocked as exc:
        if not allow_completed or exc.code != "missing_task":
            raise
        receipt = receipts.load_completed(repo, task)
        if receipt is None:
            raise
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
        projection_ready = sum(
            1
            for finding in findings
            if isinstance(finding, dict)
            and finding.get("id") in ready
            and isinstance(finding.get("records"), list)
            and bool(finding.get("records"))
        )
        lines.extend(
            [
                "GOVERNANCE-PHASE: adopt",
                f"SELECTED-FINDINGS: {', '.join(ready) or 'none ready'}",
                f"PROJECTION-READY: {projection_ready}/{len(ready)} selected findings",
                f"NEXT: invariant governance project {args.task_id}",
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
        "COVERAGE: 0/{count} selected findings dispositioned".format(count=len(selected)),
        "NEXT: run 'invariant governance project <task-id>'; edit its draft only for ambiguous mappings",
    ]


_REGISTRIES = {
    "semantic": (".invariant/SEMANTICS.yml", "records"),
    "domain": (".invariant/DOMAINS.yml", "domains"),
    "contract": (".invariant/CONTRACTS.yml", "contracts"),
    "constraint": (".invariant/CONSTRAINTS.yml", "constraints"),
}


def _coverage_value(
    audit_id: str,
    selected: list[str],
    manifest: AdoptionManifest,
    audit_findings: list[object] | None = None,
) -> dict[str, object]:
    audit_index = {
        str(finding.get("id")): finding
        for finding in audit_findings or []
        if isinstance(finding, dict) and finding.get("id")
    }
    findings: dict[str, dict[str, object]] = {
        identifier: {
            "summary": str(audit_index.get(identifier, {}).get("summary") or ""),
            "proposed": str(audit_index.get(identifier, {}).get("proposed") or ""),
            "audit_disposition": str(
                audit_index.get(identifier, {}).get("disposition") or ""
            ),
            "status": "missing",
            "records": [],
        }
        for identifier in selected
    }
    selected_set = set(selected)
    for mapping in manifest.mappings:
        unknown = sorted(set(mapping.findings) - selected_set)
        if unknown:
            raise InvariantError(
                f"Invariant: adoption mapping references unselected finding '{unknown[0]}'",
                code="invalid_adoption",
            )
        for identifier in mapping.findings:
            item = findings[identifier]
            if mapping.records:
                if item.get("status") not in {"missing", "projected"}:
                    raise InvariantError(
                        f"Invariant: finding '{identifier}' has conflicting adoption dispositions",
                        code="invalid_adoption",
                    )
                prior = item.get("records", [])
                values = [record.reference for record in mapping.records]
                item["records"] = (
                    sorted(set([*prior, *values]))
                    if isinstance(prior, list)
                    else values
                )
                item["status"] = "projected"
            elif mapping.retained_as:
                if item.get("status") != "missing":
                    raise InvariantError(
                        f"Invariant: finding '{identifier}' has conflicting adoption dispositions",
                        code="invalid_adoption",
                    )
                item.update({"status": "retained", "retained_as": mapping.retained_as})
            elif mapping.deferred:
                if item.get("status") != "missing":
                    raise InvariantError(
                        f"Invariant: finding '{identifier}' has conflicting adoption dispositions",
                        code="invalid_adoption",
                    )
                item.update({"status": "deferred", "reason": mapping.deferred})
            else:
                if item.get("status") != "missing":
                    raise InvariantError(
                        f"Invariant: finding '{identifier}' has conflicting adoption dispositions",
                        code="invalid_adoption",
                    )
                item["reason"] = mapping.unresolved
    missing = sorted(
        identifier for identifier, value in findings.items() if value.get("status") == "missing"
    )
    projected = sorted(
        {
            reference
            for value in findings.values()
            for reference in value.get("records", [])
            if isinstance(reference, str)
        }
    )
    return {
        "version": 1,
        "audit": audit_id,
        "selected_findings": selected,
        "findings": findings,
        "projected_records": projected,
        "complete": not missing,
        "missing": missing,
    }


def _project(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    receipt, session = _session(repo, args.task_id)
    if session.get("phase") not in {"decision", "adopt", "authoring"}:
        raise Blocked(
            f"Invariant: projection is unavailable in phase '{session.get('phase')}'"
        )
    audit_id = str(session.get("audit") or "")
    selected = sorted(
        str(item)
        for item in session.get("selected_findings", [])
        if isinstance(item, str)
    )
    if not selected:
        raise Blocked("Invariant: no findings are selected for projection", code="no_findings")
    candidate = _candidate_repo(repo, receipt)
    audit_raw = load_yaml(
        candidate / ".invariant" / "audits" / f"{audit_id}.yml"
    )
    audit_findings = (
        audit_raw.get("findings", []) if isinstance(audit_raw, dict) else []
    )
    manifest = (
        AdoptionManifest.load(args.input)
        if args.input
        else AdoptionManifest.from_audit(audit_id, audit_findings, selected)
    )
    authored = AdoptionManifest.from_audit(audit_id, audit_findings, selected)
    authored_by_finding = {
        identifier: {
            record.reference: record.value for record in mapping.records
        }
        for mapping in authored.mappings
        for identifier in mapping.findings
        if mapping.records
    }
    supplied_by_finding: dict[str, dict[str, object]] = {}
    for mapping in manifest.mappings:
        for identifier in mapping.findings:
            values = supplied_by_finding.setdefault(identifier, {})
            for record in mapping.records:
                values[record.reference] = record.value
    for identifier, expected in authored_by_finding.items():
        if supplied_by_finding.get(identifier) != expected:
            raise InvariantError(
                "Invariant: adoption cannot override audit-authored records for finding "
                f"'{identifier}'; amend the audit instead",
                code="invalid_adoption",
            )
    if manifest.audit != audit_id:
        raise InvariantError(
            f"Invariant: adoption manifest names audit '{manifest.audit}', expected '{audit_id}'",
            code="invalid_adoption",
        )
    coverage = _coverage_value(audit_id, selected, manifest, audit_findings)
    local = receipts.task_root(repo, args.task_id)
    local.mkdir(parents=True, exist_ok=True)
    draft = local / "governance-adoption.draft.yml"
    dump_yaml(draft, manifest.as_dict())
    dump_yaml(local / "governance-coverage.yml", coverage)
    if not coverage["complete"]:
        missing = coverage["missing"]
        session["coverage"] = coverage
        receipt["governance_run"] = session
        receipts.save(repo, args.task_id, receipt)
        raise Blocked(
            "Invariant: selected finding coverage is incomplete",
            code="incomplete_adoption_coverage",
            lines=[
                *[f"UNCOVERED: {identifier}" for identifier in missing],
                f"DRAFT: {draft}",
                "NEXT: edit the draft, then rerun governance project with --input",
            ],
            data={"coverage": coverage, "draft": str(draft)},
        )

    projected: dict[str, dict[str, object]] = {}
    for mapping in manifest.mappings:
        if mapping.retained_as:
            identifier = mapping.retained_as.removeprefix("discovery:")
            if not (candidate / ".invariant" / "discoveries" / f"{identifier}.yml").is_file():
                raise InvariantError(
                    f"Invariant: retained discovery '{identifier}' is absent from the candidate",
                    code="invalid_adoption",
                )
        for record in mapping.records:
            existing = projected.get(record.reference)
            if existing is not None and existing != record.value:
                raise InvariantError(
                    f"Invariant: projected record '{record.reference}' has conflicting definitions",
                    code="invalid_adoption",
                )
            projected[record.reference] = record.value

    documents: dict[Path, dict[str, object]] = {}
    for reference, value in projected.items():
        kind, _ = reference.split(":", 1)
        relative, collection = _REGISTRIES[kind]
        path = candidate / relative
        if path in documents:
            raw = documents[path]
        elif path.is_file():
            raw = load_yaml(path)
        else:
            raw = {"version": 1, collection: []}
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise InvariantError(f"Invariant: cannot project into invalid {relative}")
        rows = raw.get(collection, [])
        if not isinstance(rows, list):
            raise InvariantError(f"Invariant: {relative} {collection} must be a list")
        updated = [
            row
            for row in rows
            if not isinstance(row, dict) or str(row.get("id") or "") != str(value.get("id"))
        ]
        updated.append(value)
        documents[path] = {
            **raw,
            collection: sorted(updated, key=lambda row: str(row.get("id", ""))),
        }

    backups = {path: path.read_bytes() if path.is_file() else None for path in documents}
    try:
        for path, value in documents.items():
            dump_yaml(path, value)
        validation = state.validate(candidate)
        if validation[-1] != "Invariant state valid":
            raise InvariantError(
                "Invariant: projected governance is not structurally valid",
                code="invalid_adoption_projection",
                lines=validation,
            )
    except Exception:
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise

    destination = local / "governance-adoption.yml"
    if args.input and args.input.resolve() != destination.resolve():
        shutil.copyfile(args.input, destination)
    else:
        dump_yaml(destination, manifest.as_dict())
    session["phase"] = "authoring"
    session["coverage"] = coverage
    session["projected_records"] = coverage["projected_records"]
    receipt["governance_run"] = session
    receipts.save(repo, args.task_id, receipt)
    lines = [
        f"GOVERNANCE-PHASE: authoring",
        f"AUDIT: {audit_id}",
        *[
            "FINDING-COVERAGE: {identifier} — {status}{detail}".format(
                identifier=identifier,
                status=value.get("status"),
                detail=(
                    f" — {', '.join(value.get('records', []))}"
                    if value.get("records")
                    else f" — {value.get('retained_as')}"
                    if value.get("retained_as")
                    else f" — {value.get('reason')}"
                    if value.get("reason")
                    else ""
                ),
            )
            for identifier, value in coverage["findings"].items()
        ],
        f"COVERAGE: {len(selected)}/{len(selected)} selected findings dispositioned",
        f"PROJECTED: {', '.join(coverage['projected_records']) or 'none'}",
        "NEXT: review the generated projections, commit the candidate, then run task finish",
    ]
    return CommandResult(
        lines,
        {
            "coverage": coverage,
            "projected_files": [
                str(path.relative_to(candidate)) for path in documents
            ],
        },
    )


def _coverage(args: argparse.Namespace) -> CommandResult:
    repo = git.root()
    _, session = _session(repo, args.task_id, allow_completed=True)
    selected = sorted(
        str(item)
        for item in session.get("selected_findings", [])
        if isinstance(item, str)
    )
    value = (
        session["coverage"]
        if isinstance(session.get("coverage"), dict)
        else {
            "version": 1,
            "audit": str(session.get("audit") or ""),
            "selected_findings": selected,
            "findings": {
                identifier: {"status": "missing", "records": []}
                for identifier in selected
            },
            "projected_records": [],
            "complete": not selected,
            "missing": selected,
        }
    )
    lines = [
        *[
            f"FINDING-COVERAGE: {identifier} — {item.get('status')}"
            for identifier, item in value.get("findings", {}).items()
            if isinstance(item, dict)
        ],
        "COVERAGE: {covered}/{total} selected findings dispositioned".format(
            covered=len(selected) - len(value.get("missing", [])),
            total=len(selected),
        ),
    ]
    return CommandResult(lines, {"coverage": value})


def _yaml_result(value: object, name: str) -> CommandResult:
    lines = yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip().splitlines()
    return CommandResult(lines, {name: value})


def _projection_schema(_: argparse.Namespace) -> CommandResult:
    return _yaml_result(schema(), "schema")


def _projection_example(_: argparse.Namespace) -> CommandResult:
    return _yaml_result(example(), "example")


def _status(args: argparse.Namespace) -> list[str]:
    repo = git.root()
    receipt, session = _session(repo, args.task_id, allow_completed=True)
    lifecycle = receipt.get("lifecycle") if isinstance(receipt.get("lifecycle"), dict) else {}
    completed = lifecycle.get("stage") == "completed"
    lines = [
        f"GOVERNANCE-PHASE: {'completed' if completed else session.get('phase')}",
        f"AUDIT: {session.get('audit') or 'not saved'}",
    ]
    if completed:
        lines.append(f"ADOPTION-PHASE: {session.get('phase')}")
    selected = session.get("selected_findings")
    if isinstance(selected, list):
        lines.append(f"SELECTED-FINDINGS: {', '.join(str(item) for item in selected) or 'none'}")
    coverage = session.get("coverage") if isinstance(session.get("coverage"), dict) else {}
    if isinstance(selected, list):
        missing = coverage.get("missing", selected)
        missing_count = len(missing) if isinstance(missing, list) else len(selected)
        lines.append(
            f"COVERAGE: {len(selected) - missing_count}/{len(selected)} selected findings dispositioned"
        )
    projected = coverage.get("projected_records")
    if isinstance(projected, list):
        lines.append(f"PROJECTED: {', '.join(str(item) for item in projected) or 'none'}")
    lines.extend(tasks.status(repo, args.task_id))
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
