"""Read-only projections for the terminal status and global web host."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Any

import yaml

from invariant.application import InvariantApplication
from invariant.errors import InvariantError
from invariant.governance import GovernanceStore
from invariant.mechanics import git
from invariant.protocol import digest


SNAPSHOT_INTERVAL_SECONDS = 1.0
EVENT_HEARTBEAT_SECONDS = 15.0


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _last_audit(repo: Path, head: str) -> dict[str, Any]:
    files = git.tree_text_files(repo, head, ".invariant/audits")
    audits: list[dict[str, Any]] = []
    for path, text in files.items():
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(value, dict):
            audits.append(
                {
                    "id": str(value.get("id") or Path(path).stem),
                    "created_at": str(value.get("created_at") or ""),
                    "ground": str(value.get("ground") or ""),
                    "tree": str(value.get("tree") or ""),
                    "findings": len(value.get("findings", []))
                    if isinstance(value.get("findings"), list)
                    else 0,
                }
            )
    if not audits:
        return {"status": "absent", "id": "", "created_at": "", "behind": None}
    selected = max(audits, key=lambda item: (item["created_at"], item["id"]))
    head_tree = git.tree_of(repo, head)
    if selected["tree"] == head_tree or selected["ground"] == head:
        status = "fresh"
        behind: int | None = 0
    elif selected["ground"] and git.run(
        ["merge-base", "--is-ancestor", selected["ground"], head],
        cwd=repo,
        check=False,
    ).returncode == 0:
        raw = git.run(
            ["rev-list", "--count", f"{selected['ground']}..{head}"], cwd=repo
        ).stdout
        behind = int(raw)
        status = "stale"
    else:
        behind = None
        status = "diverged"
    return {**selected, "status": status, "behind": behind}


def build_snapshot(repo: Path) -> dict[str, Any]:
    application = InvariantApplication.bind(repo, principal="harness:observer")
    repository = application.repository
    target, head, policy = repository.integration()
    diagnostics: list[str] = []
    state = "valid"
    try:
        application.state_validate()
    except InvariantError as error:
        state = "invalid"
        diagnostics.append(f"{error.code}: {error.message.removeprefix('Invariant: ')}")

    try:
        governance = GovernanceStore(repository.primary_worktree).load(head)
        records = [
            {
                "id": f"{record.kind}:{record.identifier}",
                "kind": record.kind,
                "digest": record.digest,
            }
            for record in governance.records
        ]
        governance_digest = governance.digest
    except InvariantError as error:
        records = []
        governance_digest = ""
        diagnostics.append(f"{error.code}: {error.message.removeprefix('Invariant: ')}")

    tasks: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    refs = git.run(
        ["for-each-ref", "--format=%(refname)", "refs/invariant/changes"],
        cwd=repo,
        check=False,
    ).stdout.splitlines()
    for ref in refs:
        change_id = ref.removeprefix("refs/invariant/changes/")
        try:
            ledger = application.store.load(change_id)
        except InvariantError as error:
            diagnostics.append(f"{change_id}: {error.code}")
            continue
        value = ledger.state
        pending = sum(
            1
            for action in value.get("actions", {}).values()
            if action.get("status") == "pending"
        )
        task = {
            "id": change_id,
            "kind": "governance"
            if any(
                path == "repo:.invariant/config.yml"
                or path.startswith("repo:.invariant/records/")
                for path in value.get("scope", {}).get("paths", [])
            )
            else "change",
            "stage": str(value.get("stage") or "unknown"),
            "freshness": (
                "landed"
                if value.get("stage") == "completed"
                else "fresh" if value.get("base") == head else "stale"
            ),
            "target": str(value.get("target", {}).get("branch") or target),
            "pending_actions": pending,
            "ledger": ledger.head,
        }
        tasks.append(task)
        recommendation = value.get("recommendation")
        if isinstance(recommendation, dict):
            plans.append(
                {
                    "id": str(recommendation.get("id") or change_id),
                    "summary": str(value.get("intent", {}).get("statement") or change_id),
                    "valid": value.get("stage") == "completed" or value.get("base") == head,
                }
            )
        for item in value.get("evidence", []):
            if isinstance(item, dict):
                evidence.append(
                    {
                        "id": str(item.get("id") or "evidence"),
                        "summary": str(item.get("locator") or item.get("kind") or change_id),
                        "status": str(item.get("status") or "recorded"),
                        "freshness": "fresh"
                        if item.get("candidate") == (value.get("candidate") or {}).get("tree")
                        else "stale",
                    }
                )

    audit = _last_audit(repo, head)
    body: dict[str, Any] = {
        "observed_at": _timestamp(),
        "repository": {
            "name": repository.primary_worktree.name,
            "path": str(repository.primary_worktree),
            "branch": target,
            "head": head,
            "state": state,
            "intent": ",".join(policy.authority.intent.suppliers),
            "authority": ",".join(policy.authority.intent.suppliers),
            "resolution": policy.authority.resolution.delegation,
            "execution": policy.execution.transitions,
            "parallelism": policy.parallelism.maximum,
        },
        "tasks": sorted(tasks, key=lambda item: item["id"]),
        "plans": sorted(plans, key=lambda item: item["id"]),
        "leases": [],
        "processes": [],
        "evidence": evidence[-12:],
        "governance": {
            "records": records,
            "digest": governance_digest,
            "audit": audit,
            "staleness": audit["status"],
            "diagnostics": diagnostics,
        },
        "diagnostics": diagnostics,
    }
    body["revision"] = digest(
        {key: value for key, value in body.items() if key != "observed_at"}
    )
    return body


class SnapshotStore:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self._condition = threading.Condition()
        self._snapshot: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def current(self) -> dict[str, Any]:
        with self._condition:
            if self._snapshot is None:
                self._snapshot = build_snapshot(self.repo)
            return self._snapshot

    def wait(self, revision: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while (
                self._snapshot is None
                or self._snapshot.get("revision") == revision
            ) and not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._snapshot or build_snapshot(self.repo)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = build_snapshot(self.repo)
            except Exception as error:  # Keep the observer alive; the API remains inspectable.
                snapshot = {
                    "revision": digest({"error": str(error), "at": _timestamp()}),
                    "observed_at": _timestamp(),
                    "repository": {"state": "invalid"},
                    "tasks": [],
                    "plans": [],
                    "leases": [],
                    "processes": [],
                    "evidence": [],
                    "governance": {"records": [], "diagnostics": [str(error)]},
                    "diagnostics": [str(error)],
                }
            with self._condition:
                if self._snapshot is None or snapshot["revision"] != self._snapshot["revision"]:
                    self._snapshot = snapshot
                    self._condition.notify_all()
            self._stop.wait(SNAPSHOT_INTERVAL_SECONDS)
