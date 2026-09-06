from __future__ import annotations

import shutil
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from invariant.adapters.base import AdapterGate
from invariant.adapters.task_acceptance.models import (
    TaskAcceptanceContract,
    TaskAcceptanceReview,
)
from invariant.mechanics.documents import dump_yaml


class TaskAcceptanceAdapter:
    id = "task_acceptance"
    begin_stage = "awaiting-task-acceptance"
    review_stage = "awaiting-task-acceptance-review"

    @staticmethod
    def _root(task_root: Path) -> Path:
        return task_root / "adapters" / "task_acceptance"

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def begin(
        self,
        task_root: Path,
        goal_digest: str,
        source: str | None,
        state: dict[str, object] | None,
    ) -> tuple[dict[str, object] | None, AdapterGate | None]:
        if state is not None:
            stored = self._root(task_root) / "contract.yml"
            if not stored.is_file():
                return None, AdapterGate(
                    self.begin_stage,
                    "Invariant: the task acceptance contract is missing from local runtime",
                    "task_acceptance_required",
                )
            contract = TaskAcceptanceContract.load(stored)
            if contract.source_goal_digest != goal_digest:
                return None, AdapterGate(
                    self.begin_stage,
                    "Invariant: the stored task acceptance contract no longer matches the task goal",
                    "task_acceptance_goal_mismatch",
                )
            if state.get("contract_digest") != self._digest(stored):
                return None, AdapterGate(
                    self.begin_stage,
                    "Invariant: the task acceptance contract changed after task creation",
                    "task_acceptance_contract_changed",
                    ("NEXT: restore the captured contract or invalidate and restart the task",),
                )
            return state, None
        if source is None:
            return None, AdapterGate(
                self.begin_stage,
                "Invariant: the task acceptance adapter requires a local contract",
                "task_acceptance_required",
                (
                    f"GOAL-DIGEST: {goal_digest}",
                    "NEXT: create the contract from 'invariant task acceptance schema' and rerun "
                    "task begin with --acceptance-contract <file>",
                ),
            )
        contract = TaskAcceptanceContract.load(source)
        if contract.source_goal_digest != goal_digest:
            return None, AdapterGate(
                self.begin_stage,
                "Invariant: task acceptance contract does not match the task goal",
                "task_acceptance_goal_mismatch",
                (f"GOAL-DIGEST: {goal_digest}",),
            )
        destination = self._root(task_root) / "contract.yml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        return {
            "required": contract.required,
            "nodes": contract.nodes,
            "verification_level": contract.verification_level,
            "contract_digest": self._digest(destination),
        }, None

    def prepare_candidate(
        self,
        task_root: Path,
        goal_digest: str,
        candidate_tree: str,
        state: dict[str, object],
    ) -> dict[str, object]:
        required = [str(item) for item in state.get("required", ["goal"])]
        review = {
            "version": 1,
            "adapter": self.id,
            "source_goal_digest": goal_digest,
            "candidate_tree": candidate_tree,
            "results": [
                {
                    "satisfies": reference,
                    "disposition": "unresolved",
                    "prose": "Review this acceptance condition against the exact candidate tree.",
                    "evidence": [],
                }
                for reference in required
            ],
        }
        destination = self._root(task_root) / "prepared-review.yml"
        dump_yaml(destination, review)
        return {
            "adapter": self.id,
            "candidate_tree": candidate_tree,
            "review": str(destination),
            "verification_level": str(state.get("verification_level") or "targeted"),
            "required": required,
        }

    def review_candidate(
        self,
        task_root: Path,
        goal_digest: str,
        candidate_tree: str,
        source: str | None,
        state: dict[str, object],
    ) -> AdapterGate | None:
        contract = self._root(task_root) / "contract.yml"
        if not contract.is_file() or state.get("contract_digest") != self._digest(contract):
            return AdapterGate(
                self.review_stage,
                "Invariant: the task acceptance contract changed after task creation",
                "task_acceptance_contract_changed",
                ("NEXT: restore the captured contract or invalidate and restart the task",),
            )
        prepared = self._root(task_root) / "prepared-review.yml"
        selected = Path(source) if source else prepared
        if not selected.is_file():
            prepared = self.prepare_candidate(task_root, goal_digest, candidate_tree, state)
            return AdapterGate(
                self.review_stage,
                "Invariant: task acceptance review is required for the exact prospective tree",
                "task_acceptance_review_required",
                (
                    f"CANDIDATE-TREE: {candidate_tree}",
                    f"REVIEW: {prepared['review']}",
                    "NEXT: resolve every result with proportional evidence, then rerun task finish",
                ),
            )
        review = TaskAcceptanceReview.load(selected)
        if review.source_goal_digest != goal_digest or review.candidate_tree != candidate_tree:
            prepared = self.prepare_candidate(task_root, goal_digest, candidate_tree, state)
            return AdapterGate(
                self.review_stage,
                "Invariant: task acceptance review is stale for the current candidate",
                "task_acceptance_review_required",
                (
                    f"CANDIDATE-TREE: {candidate_tree}",
                    f"REVIEW: {prepared['review']}",
                    "NEXT: review the regenerated exact-tree draft, then rerun task finish",
                ),
            )
        by_reference = {item.reference: item for item in review.results}
        required = [str(item) for item in state.get("required", ["goal"])]
        missing = [reference for reference in required if reference not in by_reference]
        if missing:
            return AdapterGate(
                self.review_stage,
                f"Invariant: task acceptance review is missing {missing[0]}",
                "task_acceptance_review_required",
            )
        unresolved = [
            by_reference[reference]
            for reference in required
            if by_reference[reference].disposition != "satisfied"
        ]
        if unresolved:
            return AdapterGate(
                self.review_stage,
                f"Invariant: task acceptance {unresolved[0].reference} is {unresolved[0].disposition}",
                "task_acceptance_not_satisfied",
            )
        unsupported = [
            by_reference[reference]
            for reference in required
            if not by_reference[reference].evidence
        ]
        if unsupported:
            return AdapterGate(
                self.review_stage,
                f"Invariant: satisfied task acceptance {unsupported[0].reference} requires evidence",
                "task_acceptance_evidence_required",
                (
                    "EVIDENCE: use inspection:, test:, command:, schema:, review:, or another "
                    "inspectable locator",
                ),
            )
        destination = self._root(task_root) / "review.yml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if selected.resolve() != destination.resolve():
            shutil.copyfile(selected, destination)
        if selected.resolve() != prepared.resolve():
            shutil.copyfile(selected, prepared)
        return None

    def context(self, task_root: Path, state: dict[str, object]) -> list[str]:
        contract = self._root(task_root) / "contract.yml"
        if not contract.is_file():
            return []
        return ["# Task acceptance contract", "", *contract.read_text(encoding="utf-8").splitlines()]

    def guidance(self, stage: str) -> str:
        name = "review" if stage == self.review_stage else "contract"
        resource = files("invariant.adapters.task_acceptance").joinpath("guidance", f"{name}.md")
        return resource.read_text(encoding="utf-8").strip()


def contract_schema() -> dict[str, object]:
    node = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "prose"],
        "properties": {
            "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
            "prose": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant task acceptance contract",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "adapter", "source_goal_digest", "requirements", "verification"],
        "properties": {
            "version": {"const": 1},
            "adapter": {"const": "task_acceptance"},
            "source_goal_digest": {"type": "string", "minLength": 1},
            "requirements": {
                "type": "object",
                "additionalProperties": False,
                "required": ["goal"],
                "properties": {
                    "goal": {"type": "string", "minLength": 1},
                    "outcomes": {"type": "array", "items": node},
                    "acceptance": {"type": "array", "items": node},
                    "constraints": {"type": "array", "items": node},
                },
            },
            "verification": {
                "type": "object",
                "additionalProperties": False,
                "required": ["level", "rationale"],
                "properties": {
                    "level": {"enum": ["inspection", "targeted", "broad"]},
                    "rationale": {"type": "string", "minLength": 1},
                },
            },
        },
    }


def review_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant task acceptance review",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "adapter", "source_goal_digest", "candidate_tree", "results"],
        "properties": {
            "version": {"const": 1},
            "adapter": {"const": "task_acceptance"},
            "source_goal_digest": {"type": "string", "minLength": 1},
            "candidate_tree": {"type": "string", "minLength": 1},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["satisfies", "disposition", "prose", "evidence"],
                    "properties": {
                        "satisfies": {"type": "string", "minLength": 1},
                        "disposition": {"enum": ["satisfied", "not-satisfied", "unresolved"]},
                        "prose": {"type": "string", "minLength": 1},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "uniqueItems": True,
                        },
                    },
                },
            },
        },
    }


def examples() -> dict[str, object]:
    digest = "<from task begin>"
    return {
        "contract": {
            "version": 1,
            "adapter": "task_acceptance",
            "source_goal_digest": digest,
            "requirements": {
                "goal": "Change the button label to Save changes.",
                "outcomes": [],
                "acceptance": [{"id": "label", "prose": "The button displays Save changes."}],
                "constraints": [],
            },
            "verification": {
                "level": "inspection",
                "rationale": "This is a local presentation-only change; no durable behavior changes.",
            },
        },
        "review": {
            "version": 1,
            "adapter": "task_acceptance",
            "source_goal_digest": digest,
            "candidate_tree": "<from task assessment prepare>",
            "results": [
                {
                    "satisfies": "label",
                    "disposition": "satisfied",
                    "prose": "The candidate renders the requested label.",
                    "evidence": ["inspection:src/components/SaveButton.tsx"],
                }
            ],
        },
    }
