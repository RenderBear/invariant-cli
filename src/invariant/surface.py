"""Human-surface composition over the protocol-v1 application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from invariant.application import InvariantApplication
from invariant.errors import InvariantError
from invariant.gateway.resolution import REVIEW_KINDS
from invariant.governance import GovernanceSelection, GovernanceStore, compile_obligations
from invariant.harness import preferences
from invariant.harness.identity import authenticate_user, refusal_lines
from invariant.harness.providers import AgentProvider, invoke, invoke_change
from invariant.mechanics import config, git
from invariant.protocol import Outcome, canonical_json


USER_PRINCIPAL = "user:cli"
HARNESS_PRINCIPAL = "harness:cli"


def _user(repo: Path) -> InvariantApplication:
    """Bind direct user authority; only an authenticated interactive host may hold it."""

    return InvariantApplication.bind(
        repo, principal=USER_PRINCIPAL, authentication=authenticate_user(repo)
    )


def _harness(repo: Path) -> InvariantApplication:
    return InvariantApplication.bind(repo, principal=HARNESS_PRINCIPAL)


@dataclass(frozen=True)
class SurfaceResult:
    lines: tuple[str, ...]
    data: dict[str, Any]


def _governance_preview(repo: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """Describe changed records and their closed effects for exact-candidate acceptance."""

    candidate = state.get("candidate") or {}
    paths = [str(path).removeprefix("repo:") for path in candidate.get("paths", [])]
    if not any(path.startswith(".invariant/records/") for path in paths):
        return None
    store = GovernanceStore(repo)
    before = store.load(str(state["base"]))
    after = store.load(str(candidate["commit"]))
    before_by_id = {(record.kind, record.identifier): record for record in before.records}
    after_by_id = {(record.kind, record.identifier): record for record in after.records}
    added: list[str] = []
    changed: list[str] = []
    removed: list[str] = []
    affected = []
    records: list[dict[str, str]] = []
    directive_changes: list[dict[str, Any]] = []

    def describe(record: Any) -> str:
        if record.kind == "domain":
            return str(record.data["responsibility"])
        if record.kind in {"contract", "constraint"}:
            return str(record.data["assertion"])
        status = str(record.data.get("status") or "active")
        return f"Treats {record.data['document']} as {status} canonical meaning."

    def add_directives(record: Any, change: str) -> None:
        directive_changes.extend(
            {
                "record": f"{record.kind}:{record.identifier}",
                "change": change,
                **directive.as_dict(),
            }
            for directive in record.directives
        )

    for key, record in sorted(after_by_id.items()):
        prior = before_by_id.get(key)
        if prior is None:
            added.append(f"{record.kind}:{record.identifier}")
            affected.append(record)
            records.append(
                {
                    "change": "added",
                    "kind": record.kind,
                    "id": record.identifier,
                    "summary": describe(record),
                    "path": record.path,
                    "authority": "pending",
                }
            )
            add_directives(record, "added")
        elif prior.digest != record.digest:
            changed.append(f"{record.kind}:{record.identifier}")
            affected.append(record)
            records.append(
                {
                    "change": "changed",
                    "kind": record.kind,
                    "id": record.identifier,
                    "summary": describe(record),
                    "path": record.path,
                    "authority": prior.authority,
                }
            )
            prior_directives = {
                item.identifier: item.as_dict() for item in prior.directives
            }
            current_directives = {
                item.identifier: item.as_dict() for item in record.directives
            }
            for identifier in sorted(set(prior_directives) | set(current_directives)):
                before_directive = prior_directives.get(identifier)
                after_directive = current_directives.get(identifier)
                if before_directive == after_directive:
                    continue
                directive_changes.append(
                    {
                        "record": f"{record.kind}:{record.identifier}",
                        "change": (
                            "added"
                            if before_directive is None
                            else "removed" if after_directive is None else "changed"
                        ),
                        **(after_directive or before_directive or {}),
                    }
                )
    for key, record in sorted(before_by_id.items()):
        if key not in after_by_id:
            removed.append(f"{record.kind}:{record.identifier}")
            records.append(
                {
                    "change": "removed",
                    "kind": record.kind,
                    "id": record.identifier,
                    "summary": describe(record),
                    "path": record.path,
                    "authority": record.authority,
                }
            )
            add_directives(record, "removed")

    selection = GovernanceSelection.create(
        affected,
        {record.reference: {"changed-in-candidate"} for record in affected},
    )
    policy = config.resolve_at(
        repo,
        str(candidate["commit"]),
        str(state["target"]["branch"]),
    )
    obligations = compile_obligations(policy, selection).as_dict()
    return {
        "candidate": str(candidate["tree"]),
        "added": added,
        "changed": changed,
        "removed": removed,
        "records": records,
        "record_sources": [record.reference for record in affected],
        "authorities": sorted({record["authority"] for record in records if record["authority"] != "pending"}),
        "directives": directive_changes,
        "consequences": obligations,
    }


def _directive_effect(directive: dict[str, Any]) -> str:
    kind = str(directive.get("kind") or "")
    if kind == "deny-capability":
        return f"Blocks {directive['capability']}."
    if kind == "require-resolution":
        return f"Requires {directive['resolver']} resolution before {directive['capability']}."
    if kind == "require-review":
        return f"Requires {directive['mode']} review."
    if kind == "require-verifier":
        return f"Requires the check {directive['locator']}."
    if kind == "serialize":
        return f"Prevents concurrent work across {', '.join(directive['on'])}."
    if kind == "limit-parallelism":
        return f"Limits parallel work to {directive['maximum']} units."
    if kind == "require-containment":
        return f"Requires managed containment for {directive['capability']}."
    return kind


def _decision_lines(preview: dict[str, Any]) -> tuple[str, ...]:
    records = list(preview["records"])
    kind_names = {
        "semantic": ("design meaning", "design meanings"),
        "domain": ("ownership area", "ownership areas"),
        "contract": ("interface contract", "interface contracts"),
        "constraint": ("rule", "rules"),
    }
    counts: dict[str, int] = {}
    for record in records:
        counts[record["kind"]] = counts.get(record["kind"], 0) + 1
    composition = " · ".join(
        f"{count} {kind_names.get(kind, (kind, kind + 's'))[count != 1]}"
        for kind, count in sorted(counts.items())
    )
    noun = "record" if len(records) == 1 else "records"
    lines = [
        f"{len(records)} {noun} will define how Invariant understands and governs "
        f"this repository ({composition}).",
        "",
    ]
    for record in records[:6]:
        kind_name = kind_names.get(
            record["kind"], (record["kind"], record["kind"] + "s")
        )[0]
        lines.append(
            f"{record['change'].capitalize()} {kind_name} “{record['id']}” — "
            f"{record['summary']}"
        )
    if len(records) > 6:
        lines.append(f"And {len(records) - 6} more records; :details shows every one.")

    directives = list(preview["directives"])
    if directives:
        lines.extend(["", "Material effects:"])
        lines.extend(
            f"• {item['change'].capitalize()} rule: {_directive_effect(item)}"
            for item in directives[:4]
        )
        if len(directives) > 4:
            lines.append(f"• Plus {len(directives) - 4} more; :details shows every rule.")
    verifier_count = len(
        preview["consequences"].get("required_verifiers", [])
    )
    lines.extend(
        [
            "",
            "All record links and candidate structure are valid."
            + (
                f" The baseline would require {verifier_count} repository checks "
                "on affected future changes."
                if verifier_count
                else ""
            ),
            "Accepting is bound to this exact candidate; later edits require a new decision.",
            "",
            "Type :accept to establish it.",
            "Type :details to inspect every record, rule, source, and the Git identity.",
        ]
    )
    return tuple(lines)


def _preview_detail_lines(preview: dict[str, Any] | None) -> tuple[str, ...]:
    if preview is None:
        return ()
    consequences = preview["consequences"]
    record_sources = set(preview["record_sources"])
    effects: list[str] = []
    effects.extend(
        f"context {name}" for name in consequences.get("selected_context", [])
    )
    effects.extend(
        f"deny {name}"
        for name, sources in consequences.get("denied_capabilities", {}).items()
        if record_sources.intersection(sources)
    )
    effects.extend(
        f"resolve {name} by {resolver}"
        for name, resolver in consequences.get("required_resolution", {}).items()
    )
    effects.extend(f"{mode} review" for mode in consequences.get("required_reviews", []))
    effects.extend(f"verify {value}" for value in consequences.get("required_verifiers", []))
    effects.extend(f"serialize {value}" for value in consequences.get("serialize_on", []))
    if consequences.get("parallel_limit") is not None and any(
        directive.get("kind") == "limit-parallelism"
        for directive in preview["directives"]
    ):
        effects.append(f"parallelism ≤ {consequences['parallel_limit']}")
    lines = [f"CANDIDATE: {preview['candidate']}"]
    lines.extend(
        f"RECORD: {item['change']} {item['kind']}:{item['id']} in {item['path']} — "
        f"{item['summary']}"
        for item in preview["records"]
    )
    lines.extend(
        f"RULE: {item['change']} in {item['record']} — {_directive_effect(item)}"
        for item in preview["directives"]
    )
    lines.extend(
        [
            f"CONSEQUENCES: {', '.join(effects) or 'context only'}",
            f"GROUNDING: {', '.join(preview['authorities']) or 'removed records only'}",
        ]
    )
    return tuple(lines)


def settings(repo: Path) -> SurfaceResult:
    application = _harness(repo)
    policy = application.repository.policy
    values = {
        "authority.intent.suppliers": ",".join(policy.authority.intent.suppliers),
        "authority.resolution.delegation": policy.authority.resolution.delegation,
        "integration_branch": policy.integration_branch,
        "publication": policy.publication,
        "parallelism.maximum": str(policy.parallelism.maximum),
        "harness": preferences.repo_harness(repo),
        "mode": preferences.session_mode(repo),
    }
    return SurfaceResult(
        tuple(f"{key.upper()}: {value}" for key, value in values.items()),
        {"settings": values},
    )


def set_value(repo: Path, key: str, value: str) -> SurfaceResult:
    """Apply one local preference or land one deterministic governed policy change."""

    if key == "harness":
        preferences.set_repo_harness(repo, value)
        return SurfaceResult(
            (f"SETTING: harness", f"VALUE: {value}", "SCOPE: this clone"),
            {"key": key, "value": value, "scope": "clone"},
        )
    if key == "mode":
        preferences.set_session_mode(repo, value)
        return SurfaceResult(
            (f"SETTING: mode", f"VALUE: {value}", "SCOPE: this clone"),
            {"key": key, "value": value, "scope": "clone"},
        )

    user = _user(repo)
    target, base, _ = user.repository.integration()
    canonical, document, changed = config.updated_document(
        repo, base, target, key, value
    )
    if not changed:
        return SurfaceResult(
            (f"SETTING: {canonical}", f"VALUE: {value}", "STATUS: unchanged"),
            {"key": canonical, "value": value, "changed": False},
        )

    suffix = uuid.uuid4().hex[:12]
    change_id = f"policy-{canonical.replace('.', '-')}-{suffix}"
    attempt_id = f"policy-{suffix}"
    operation = f"set-{suffix}"
    statement = f"Set Invariant policy {canonical} to {value}"
    user.change_open(
        change_id,
        intent=statement,
        supplier=USER_PRINCIPAL,
        paths=[config.CONFIG_PATH.as_posix()],
        operation_id=f"{operation}-open",
    )
    user.change_recommend(change_id, operation_id=f"{operation}-recommend")

    worker = InvariantApplication.bind(repo, principal=HARNESS_PRINCIPAL)
    create_token = _grant(
        worker,
        change_id,
        "worktree.create",
        f"change/{attempt_id}",
        operation_id=f"{operation}-grant-create",
        unit="change",
        attempt=attempt_id,
    )
    created = worker.work_create(
        change_id,
        unit_id="change",
        attempt_id=attempt_id,
        actor=HARNESS_PRINCIPAL,
        token=create_token,
        operation_id=f"{operation}-create",
    )
    _grant(
        worker,
        change_id,
        "worktree.write",
        attempt_id,
        operation_id=f"{operation}-grant-write",
        unit="change",
        attempt=attempt_id,
    )
    worktree = Path(str(created.result["attempt"]["worktree"]))
    config.dump_config_yaml(worktree / config.CONFIG_PATH, document)
    git.run(["add", "--", config.CONFIG_PATH.as_posix()], cwd=worktree)
    git.run(["commit", "-q", "-m", statement], cwd=worktree)
    worker.work_submit(
        change_id,
        attempt_id=attempt_id,
        actor=HARNESS_PRINCIPAL,
        operation_id=f"{operation}-submit",
    )
    converge_token = _grant(
        worker,
        change_id,
        "candidate.converge",
        attempt_id,
        operation_id=f"{operation}-grant-converge",
        attempt=attempt_id,
    )
    worker.candidate_converge(
        change_id,
        attempt_id=attempt_id,
        token=converge_token,
        operation_id=f"{operation}-converge",
    )
    worker.candidate_evidence(
        change_id, tokens={}, operation_id=f"{operation}-evidence"
    )
    candidate = worker.store.load(change_id).state["candidate"]
    requested = worker.capability_request(
        change_id,
        capability="integration.land",
        actor=HARNESS_PRINCIPAL,
        resource=candidate["tree"],
        operation_id=f"{operation}-request-authority",
    )
    action = requested.result.get("action")
    if not isinstance(action, dict):
        raise InvariantError(
            "Invariant: governed policy change did not request user acceptance",
            code="authority_required",
        )
    user.action_respond(
        change_id,
        str(action["id"]),
        response={"bindings": action["bindings"], "resolution": "accepted"},
        actor=USER_PRINCIPAL,
        operation_id=f"{operation}-accept",
    )
    land_token = _grant(
        worker,
        change_id,
        "integration.land",
        candidate["tree"],
        operation_id=f"{operation}-grant-land",
    )
    worker.integration_land(
        change_id,
        token=land_token,
        operation_id=f"{operation}-land",
        subject=statement,
    )
    landed = worker.store.load(change_id).state
    commit = str(landed["landing"]["commit"])
    _cleanup(user, change_id, landed, operation)
    return SurfaceResult(
        (
            f"SETTING: {canonical}",
            f"VALUE: {value}",
            "SCOPE: repository policy",
            f"CHANGE: {change_id}",
            f"COMMIT: {commit}",
            "STATUS: landed",
        ),
        {
            "key": canonical,
            "value": value,
            "scope": "repository",
            "change": change_id,
            "commit": commit,
            "changed": True,
        },
    )


def _grant(
    application: InvariantApplication,
    change_id: str,
    capability: str,
    resource: str,
    *,
    operation_id: str,
    unit: str | None = None,
    attempt: str | None = None,
) -> str:
    result = application.capability_request(
        change_id,
        capability=capability,
        actor=application.store.principal,
        resource=resource,
        unit=unit,
        attempt=attempt,
        operation_id=operation_id,
    )
    token = result.result.get("token")
    if result.outcome is not Outcome.READY or not isinstance(token, str):
        raise InvariantError(
            f"Invariant: {capability} was not granted",
            code="capability_required",
            data=result.result,
        )
    return token


def _cleanup(
    application: InvariantApplication,
    change_id: str,
    state: dict[str, Any],
    operation: str,
) -> None:
    refs = sorted(
        {
            *(str(item["ref"]) for item in state.get("attempts", {}).values()),
            f"refs/invariant/candidates/{change_id}",
        }
    )
    token = _grant(
        application,
        change_id,
        "work.discard",
        canonical_json(refs),
        operation_id=f"{operation}-grant-cleanup",
    )
    application.work_discard(
        change_id,
        refs=refs,
        token=token,
        operation_id=f"{operation}-cleanup",
    )


def execute_agent_change(
    repo: Path,
    provider: AgentProvider,
    session_id: str,
    intent: str,
    paths: list[str],
    *,
    timeout: int = 1800,
) -> SurfaceResult:
    """Run one conversational write through isolated execution and exact landing."""

    suffix = uuid.uuid4().hex[:12]
    change_id = f"session-{session_id.removeprefix('s-')}-{suffix}"
    attempt_id = f"work-{suffix}"
    operation = f"chat-{suffix}"
    claims = paths or ["."]
    user = _user(repo)
    user.change_open(
        change_id,
        intent=intent,
        supplier=USER_PRINCIPAL,
        paths=claims,
        operation_id=f"{operation}-open",
    )
    user.change_recommend(change_id, operation_id=f"{operation}-recommend")

    author = f"agent:{provider.value}/{session_id}"
    worker = InvariantApplication.bind(repo, principal=author)
    create_token = _grant(
        worker,
        change_id,
        "worktree.create",
        f"change/{attempt_id}",
        operation_id=f"{operation}-grant-create",
        unit="change",
        attempt=attempt_id,
    )
    created = worker.work_create(
        change_id,
        unit_id="change",
        attempt_id=attempt_id,
        actor=author,
        token=create_token,
        operation_id=f"{operation}-create",
    )
    _grant(
        worker,
        change_id,
        "worktree.write",
        attempt_id,
        operation_id=f"{operation}-grant-write",
        unit="change",
        attempt=attempt_id,
    )
    worktree = Path(str(created.result["attempt"]["worktree"]))
    starting_tip = git.resolve(worktree, "HEAD")
    execution = invoke_change(
        provider,
        worktree,
        (
            "Implement the following user-supplied intent in this isolated Invariant "
            "worktree. Do not commit, move refs, publish, or edit .invariant/runtime. "
            "Stay within these claims: "
            f"{', '.join(claims)}.\n\nIntent:\n{intent.strip()}"
        ),
        timeout=timeout,
    )
    if git.resolve(worktree, "HEAD") != starting_tip:
        raise InvariantError(
            "Invariant: the execution agent moved its worktree ref",
            code="unauthorized_ref_movement",
            data={"change": change_id},
        )
    changed = git.changed_paths(worktree)
    if not changed:
        raise InvariantError(
            "Invariant: the execution agent produced no repository change",
            code="empty_candidate",
            data={"change": change_id},
        )
    git.run(["add", "-A"], cwd=worktree)
    git.run(["commit", "-q", "-m", intent.strip().splitlines()[0][:72]], cwd=worktree)
    worker.work_submit(
        change_id,
        attempt_id=attempt_id,
        actor=author,
        operation_id=f"{operation}-submit",
    )
    converge_token = _grant(
        worker,
        change_id,
        "candidate.converge",
        attempt_id,
        operation_id=f"{operation}-grant-converge",
        attempt=attempt_id,
    )
    worker.candidate_converge(
        change_id,
        attempt_id=attempt_id,
        token=converge_token,
        operation_id=f"{operation}-converge",
    )
    state = worker.store.load(change_id).state
    required = state.get("governance", {}).get("obligations", {}).get(
        "required_verifiers", []
    )
    verifier_tokens = {
        str(locator): _grant(
            worker,
            change_id,
            "verification.run",
            str(locator),
            operation_id=f"{operation}-verify-{index}",
        )
        for index, locator in enumerate(required)
    }
    worker.candidate_evidence(
        change_id,
        tokens=verifier_tokens,
        operation_id=f"{operation}-evidence",
    )
    state = worker.store.load(change_id).state
    candidate = state["candidate"]
    preview = _governance_preview(repo, state)
    landing = _harness(repo)
    resolution: dict[str, Any] | None = None
    # Walk the resolution list. A secondary agent resolves item by item; anything assigned to
    # the user returns the same list for the host to present.
    for round_index in range(8):
        items = landing.change_pending(change_id).result["pending"]
        if any(item["resolver"] == "user" for item in items):
            return _pending_result(
                change_id, candidate["tree"], items, preview, execution.message
            )
        for item in items:
            resolved = _resolve_item(
                repo,
                provider,
                worktree,
                change_id,
                item,
                preview,
                f"{operation}-resolve-{round_index}-{item['index']}",
                timeout=timeout,
            )
            if item["kind"] == "accept-governance":
                resolution = resolved
        requested = landing.capability_request(
            change_id,
            capability="integration.land",
            actor=HARNESS_PRINCIPAL,
            resource=candidate["tree"],
            operation_id=f"{operation}-request-land-{round_index}",
        )
        if not isinstance(requested.result.get("action"), dict):
            break
    else:
        raise InvariantError(
            "Invariant: the resolution list did not converge",
            code="authority_required",
            data={"change": change_id},
        )
    token = requested.result.get("token")
    if not isinstance(token, str):
        raise InvariantError(
            "Invariant: exact candidate is not ready to land",
            code="capability_required",
            data=requested.result,
        )
    landing.integration_land(
        change_id,
        token=token,
        operation_id=f"{operation}-land",
        subject=intent.strip().splitlines()[0][:72],
    )
    completed = landing.store.load(change_id).state
    commit = str(completed["landing"]["commit"])
    _cleanup(user, change_id, completed, operation)
    if preview is not None:
        record_count = len(preview["records"])
        lines = (
            f"CHANGE: {change_id}",
            f"BASELINE: {record_count} governance records accepted",
            "RESOLUTION: secondary agent",
            f"REVIEW: {resolution['summary'] if resolution else 'accepted'}",
            f"COMMIT: {commit}",
            "STATUS: landed",
        )
    else:
        lines = (
            f"CHANGE: {change_id}",
            f"FILES: {', '.join(changed)}",
            f"COMMIT: {commit}",
            "STATUS: landed",
        )
    return SurfaceResult(
        lines,
        {
            "change": change_id,
            "paths": changed,
            "commit": commit,
            "pending": False,
            "message": execution.message,
            "governance": preview,
            "resolution": resolution,
        },
    )


def _resolve_review(
    repo: Path,
    provider: AgentProvider,
    worktree: Path,
    change_id: str,
    action: dict[str, Any],
    operation: str,
    *,
    timeout: int,
) -> None:
    reviewer = f"agent:{provider.value}/review-{uuid.uuid4().hex[:12]}"
    application = InvariantApplication.bind(repo, principal=reviewer)
    token = _grant(
        application,
        change_id,
        "intent.resolve",
        str(action["id"]),
        operation_id=f"{operation}-grant",
    )
    reviewed = invoke(
        provider,
        worktree,
        (
            "Review this exact candidate independently against the supplied user intent "
            "and repository governance. Inspect the worktree. Do not modify it. Return an "
            "accepted verdict only when no material defect remains.\n\n"
            f"Intent: {action.get('context', {}).get('intent', {}).get('statement', '')}"
        ),
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["verdict", "summary", "defects"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["accepted", "rejected", "uncertain"],
                },
                "summary": {"type": "string"},
                "defects": {"type": "array", "items": {"type": "string"}},
            },
        },
        timeout=timeout,
    )
    response = {
        "bindings": action["bindings"],
        "verdict": reviewed.response.get("verdict"),
        "summary": reviewed.response.get("summary"),
        "defects": reviewed.response.get("defects", []),
    }
    application.action_respond(
        change_id,
        str(action["id"]),
        response=response,
        actor=reviewer,
        token=token,
        operation_id=f"{operation}-respond",
    )
    if response["verdict"] != "accepted":
        raise InvariantError(
            "Invariant: secondary review did not accept the candidate",
            code="review_not_accepted",
            data={"change": change_id, "review": response},
        )


def _resolve_governance(
    repo: Path,
    provider: AgentProvider,
    worktree: Path,
    change_id: str,
    action: dict[str, Any],
    preview: dict[str, Any] | None,
    operation: str,
    *,
    timeout: int,
) -> dict[str, Any]:
    """Obtain one independent, action-bound semantic resolution."""

    resolver = f"agent:{provider.value}/resolution-{uuid.uuid4().hex[:12]}"
    application = InvariantApplication.bind(repo, principal=resolver)
    token = _grant(
        application,
        change_id,
        "intent.resolve",
        str(action["id"]),
        operation_id=f"{operation}-grant",
    )
    resolved = invoke(
        provider,
        worktree,
        (
            "Act as the independent semantic resolver for this exact governance candidate. "
            "You did not author it. Inspect the candidate records, their repository evidence, "
            "the current accepted policy, and the code and design material they describe. Do "
            "not modify the worktree. Accept only if the proposed records are minimal, accurate, "
            "evidence-backed, internally consistent, and their closed rules are appropriate. "
            "Reject if a material issue remains. Give a concise plain-language summary for the "
            "repository user; do not reproduce YAML, locators, hashes, or the drafting prompt.\n\n"
            f"Bound proposal:\n{canonical_json(preview or {})}"
        ),
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["resolution", "summary", "concerns"],
            "properties": {
                "resolution": {
                    "type": "string",
                    "enum": ["accepted", "rejected"],
                },
                "summary": {"type": "string", "minLength": 1},
                "concerns": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        timeout=timeout,
    )
    response = {
        "bindings": action["bindings"],
        "resolution": resolved.response.get("resolution"),
        "summary": resolved.response.get("summary"),
        "defects": resolved.response.get("concerns", []),
    }
    application.action_respond(
        change_id,
        str(action["id"]),
        response=response,
        actor=resolver,
        token=token,
        operation_id=f"{operation}-respond",
    )
    if response["resolution"] != "accepted":
        raise InvariantError(
            "Invariant: the independent resolver rejected the governance candidate",
            code="governance_not_accepted",
            data={"change": change_id, "resolution": response},
        )
    return response


def _pending_lines(items: list[dict[str, Any]]) -> tuple[str, ...]:
    lines: list[str] = []
    for item in items:
        lines.append(f"{item['index']}. {item['title']} · resolver: {item['resolver']}")
        lines.extend(f"   {line}" for line in item["brief"])
    if items:
        lines.extend(
            [
                "",
                "Type :resolve N accept|reject [note] to answer one item.",
                "Type :accept to accept every remaining item and land.",
                "Type :details to inspect the records, rules, and Git identity.",
            ]
        )
    return tuple(lines)


def _pending_result(
    change_id: str,
    candidate: str,
    items: list[dict[str, Any]],
    preview: dict[str, Any] | None,
    message: str = "",
) -> SurfaceResult:
    if preview is not None:
        decision_lines = (*_decision_lines(preview), "", *_pending_lines(items))
        decision_title = "Governance decision required"
    elif any(item["kind"] == "accept-governance" for item in items) and any(
        str(item.get("for_capability")) == "integration.land" for item in items
    ):
        decision_lines = (
            "This candidate changes accepted repository policy.",
            "The policy change requires your direct authority and is bound to one Git tree.",
            "",
            *_pending_lines(items),
        )
        decision_title = "Policy decision required"
    else:
        decision_lines = _pending_lines(items)
        decision_title = "Resolution required"
    return SurfaceResult(
        decision_lines,
        {
            "change": change_id,
            "candidate": candidate,
            "action": {"id": items[0]["id"], "kind": items[0]["kind"]} if items else None,
            "items": items,
            "governance": preview,
            "pending": True,
            "message": message,
            "decision_title": decision_title,
        },
    )


def _resolve_item(
    repo: Path,
    provider: AgentProvider,
    worktree: Path,
    change_id: str,
    item: dict[str, Any],
    preview: dict[str, Any] | None,
    operation: str,
    *,
    timeout: int,
) -> dict[str, Any] | None:
    action = _harness(repo).store.load(change_id).state["actions"][item["id"]]
    if item["kind"] in REVIEW_KINDS:
        _resolve_review(repo, provider, worktree, change_id, action, operation, timeout=timeout)
        return None
    return _resolve_governance(
        repo, provider, worktree, change_id, action, preview, operation, timeout=timeout
    )


def pending_list(repo: Path, change_id: str) -> SurfaceResult:
    """The ordered list of what the user must resolve for one change."""

    application = _harness(repo)
    items = application.change_pending(change_id).result["pending"]
    state = application.store.load(change_id).state
    preview = _governance_preview(repo, state) if state.get("candidate") else None
    if not items:
        return SurfaceResult(
            (f"CHANGE: {change_id}", f"STAGE: {state['stage']}", "PENDING: nothing"),
            {"change": change_id, "items": [], "pending": False, "governance": preview},
        )
    return _pending_result(change_id, str(state["candidate"]["tree"]), items, preview)


def pending_details(repo: Path, change_id: str) -> SurfaceResult:
    """Return the inspectable detail behind the pending decisions of one change."""

    application = _harness(repo)
    state = application.store.load(change_id).state
    items = application.change_pending(change_id).result["pending"]
    if not items:
        raise InvariantError(
            f"Invariant: change '{change_id}' has no pending decision",
            code="invalid_invocation",
        )
    preview = _governance_preview(repo, state)
    lines = _preview_detail_lines(preview)
    worktrees = [
        str(value.get("worktree"))
        for value in state.get("attempts", {}).values()
        if value.get("worktree")
    ]
    if lines and worktrees:
        lines = (*lines, f"WORKTREE: {worktrees[-1]}")
    if not lines:
        candidate = state.get("candidate") or {}
        lines = (
            f"CANDIDATE: {candidate.get('tree', '—')}",
            f"INTENT: {state.get('intent', {}).get('statement', '—')}",
        )
    return SurfaceResult(
        (*lines, "", *_pending_lines(items)),
        {"change": change_id, "items": items, "governance": preview, "pending": True},
    )


def resolve_pending(
    repo: Path,
    change_id: str,
    index: int,
    decision: str,
    note: str = "",
) -> SurfaceResult:
    """Supply the user's answer to one item of the resolution list; land when nothing remains."""

    if decision not in {"accepted", "rejected"}:
        raise InvariantError(
            "Invariant: a resolution is accepted or rejected", code="invalid_invocation"
        )
    user = _user(repo)
    items = user.change_pending(change_id).result["pending"]
    item = next((value for value in items if value["index"] == index), None)
    if item is None:
        raise InvariantError(
            f"Invariant: change '{change_id}' has no pending item {index}",
            code="invalid_invocation",
        )
    suffix = uuid.uuid4().hex[:12]
    response: dict[str, Any] = {"bindings": item["bindings"]}
    if item["response"] == "verdict":
        response.update(
            {"verdict": decision, "summary": note or f"{decision} by the user", "defects": []}
        )
    else:
        response.update({"resolution": decision, "summary": note or f"{decision} by the user"})
    user.action_respond(
        change_id,
        str(item["id"]),
        response=response,
        actor=USER_PRINCIPAL,
        operation_id=f"resolve-{suffix}",
    )
    if decision == "rejected":
        return SurfaceResult(
            (f"CHANGE: {change_id}", f"ITEM: {index} rejected", "STATUS: candidate retained"),
            {"change": change_id, "pending": False, "rejected": True},
        )
    return _land_if_ready(repo, change_id, user, suffix)


def _land_if_ready(
    repo: Path, change_id: str, user: InvariantApplication, suffix: str
) -> SurfaceResult:
    landing = _harness(repo)
    state = landing.store.load(change_id).state
    candidate = state["candidate"]
    requested = landing.capability_request(
        change_id,
        capability="integration.land",
        actor=HARNESS_PRINCIPAL,
        resource=candidate["tree"],
        operation_id=f"resolve-{suffix}-grant-land",
    )
    token = requested.result.get("token")
    if not isinstance(token, str):
        items = landing.change_pending(change_id).result["pending"]
        if items:
            return _pending_result(
                change_id, str(candidate["tree"]), items, _governance_preview(repo, state)
            )
        raise InvariantError(
            "Invariant: exact candidate is not ready to land",
            code="capability_required",
            data=requested.result,
        )
    landing.integration_land(
        change_id,
        token=token,
        operation_id=f"resolve-{suffix}-land",
    )
    completed = landing.store.load(change_id).state
    commit = str(completed["landing"]["commit"])
    _cleanup(user, change_id, completed, f"resolve-{suffix}")
    return SurfaceResult(
        (f"CHANGE: {change_id}", f"COMMIT: {commit}", "STATUS: landed"),
        {"change": change_id, "commit": commit, "pending": False},
    )


def accept_pending(repo: Path, change_id: str) -> SurfaceResult:
    """Accept every remaining item of the resolution list with direct user authority."""

    result: SurfaceResult | None = None
    for _ in range(16):
        items = _harness(repo).change_pending(change_id).result["pending"]
        if not items:
            break
        result = resolve_pending(repo, change_id, items[0]["index"], "accepted")
        if not result.data.get("pending"):
            return result
    if result is None:
        return _land_if_ready(repo, change_id, _user(repo), uuid.uuid4().hex[:12])
    return result
