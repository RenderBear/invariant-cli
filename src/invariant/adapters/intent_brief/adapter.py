from __future__ import annotations

import shutil
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any

from invariant.adapters.base import (
    CANDIDATE_EVIDENCED,
    TASK_CREATED,
    HookContext,
    HookRequest,
    HookResult,
)
from invariant.adapters.intent_brief.models import IntentBrief, IntentReview
from invariant.errors import Blocked, UsageError


class IntentBriefAdapter:
    id = "intent_brief"

    @staticmethod
    def _root(task_root: Path) -> Path:
        return task_root / "adapters" / "intent_brief"

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _request(
        self,
        context: HookContext,
        *,
        kind: str,
        prompt: str,
        schema: dict[str, Any],
        request_context: dict[str, Any],
    ) -> HookRequest:
        return HookRequest(
            id=f"{self.id}:{context.phase}",
            adapter=self.id,
            phase=context.phase,
            kind=kind,
            prompt=prompt,
            input_schema=schema,
            context=request_context,
        )

    def handle(
        self,
        context: HookContext,
        state: dict[str, Any] | None,
        source: str | None,
    ) -> HookResult:
        current = dict(state or {})
        root = self._root(context.task_root)
        root.mkdir(parents=True, exist_ok=True)
        if context.phase == TASK_CREATED:
            return self._expand(context, current, source)
        if context.phase == CANDIDATE_EVIDENCED:
            return self._review(context, current, source)
        return HookResult(current)

    def _expand(
        self,
        context: HookContext,
        state: dict[str, Any],
        source: str | None,
    ) -> HookResult:
        destination = self._root(context.task_root) / "brief.yml"
        if source is None:
            if destination.is_file() and state.get("brief_digest") == self._digest(destination):
                brief = IntentBrief.load(destination)
                if not brief.unanswered:
                    return HookResult(
                        state,
                        artifacts=({"kind": "intent_brief", "id": "intent-brief"},),
                    )
            request = self._request(
                context,
                kind="expand_intent",
                prompt=(
                    "Expand the original goal into a concise prose intent brief. Ask only questions "
                    "whose answers would materially change implementation or acceptance."
                ),
                schema=intent_brief_schema(),
                request_context={"goal": context.goal, "goal_digest": context.goal_digest},
            )
            return HookResult({**state, "status": "awaiting_brief"}, (request,))
        brief = IntentBrief.load(source)
        if brief.source_goal_digest != context.goal_digest:
            raise UsageError("Invariant: intent brief does not match the task goal")
        if Path(source).resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        digest = self._digest(destination)
        updated = {
            **state,
            "status": "awaiting_answers" if brief.unanswered else "ready",
            "brief_digest": digest,
        }
        artifacts = ({"kind": "intent_brief", "id": "intent-brief", "digest": digest},)
        if brief.unanswered:
            request = self._request(
                context,
                kind="answer_questions",
                prompt="Answer the material questions, update the same intent brief, and resubmit it.",
                schema=intent_brief_schema(),
                request_context={
                    "questions": [
                        {"id": item.identifier, "prompt": item.prompt}
                        for item in brief.unanswered
                    ]
                },
            )
            return HookResult(updated, (request,), artifacts)
        return HookResult(updated, artifacts=artifacts)

    def _review(
        self,
        context: HookContext,
        state: dict[str, Any],
        source: str | None,
    ) -> HookResult:
        brief_path = self._root(context.task_root) / "brief.yml"
        if not brief_path.is_file() or state.get("brief_digest") != self._digest(brief_path):
            raise Blocked("Invariant: intent brief is missing or changed", code="stale_intent_brief")
        brief = IntentBrief.load(brief_path)
        if brief.unanswered:
            raise Blocked(
                "Invariant: intent brief still has unanswered material questions",
                code="intent_questions_unanswered",
            )
        candidate = context.candidate_tree or ""
        destination = self._root(context.task_root) / "review.yml"
        if source is None:
            if (
                destination.is_file()
                and state.get("reviewed_tree") == candidate
                and state.get("review_digest") == self._digest(destination)
            ):
                return HookResult(
                    state,
                    artifacts=({"kind": "intent_review", "id": "intent-review"},),
                )
            request = self._request(
                context,
                kind="review_intent",
                prompt=(
                    "Review the exact candidate against the entire intent brief and return one "
                    "verdict, a substantive summary, and only genuine exceptions."
                ),
                schema=intent_review_schema(),
                request_context={
                    "candidate_tree": candidate,
                    "goal_digest": context.goal_digest,
                    "brief_digest": str(state.get("brief_digest") or ""),
                    "brief": brief.brief,
                    "evidence": list(context.evidence),
                },
            )
            return HookResult({**state, "status": "awaiting_review"}, (request,))
        review = IntentReview.load(source)
        if (
            review.source_goal_digest != context.goal_digest
            or review.brief_digest != state.get("brief_digest")
            or review.candidate_tree != candidate
        ):
            raise Blocked(
                "Invariant: intent review is stale for the current goal, brief, or candidate",
                code="stale_intent_review",
            )
        if review.verdict != "accepted" or review.exceptions:
            raise Blocked(
                "Invariant: intent review must accept the candidate without unresolved exceptions",
                code="intent_not_accepted",
            )
        if Path(source).resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        digest = self._digest(destination)
        return HookResult(
            {
                **state,
                "status": "reviewed",
                "reviewed_tree": candidate,
                "review_digest": digest,
                "review_summary": review.summary,
            },
            artifacts=({"kind": "intent_review", "id": "intent-review", "digest": digest},),
        )

    def context(self, task_root: Path, state: dict[str, Any]) -> list[str]:
        path = self._root(task_root) / "brief.yml"
        if not path.is_file():
            return []
        brief = IntentBrief.load(path)
        lines = ["# Intent brief", "", brief.brief]
        if brief.questions:
            lines.extend(["", "## Material questions"])
            for item in brief.questions:
                lines.append(f"- {item.prompt} — {item.answer or 'unanswered'}")
        return lines

    def guidance(self, phase: str) -> str:
        name = "review" if phase == CANDIDATE_EVIDENCED else "expand"
        resource = files("invariant.adapters.intent_brief").joinpath("guidance", f"{name}.md")
        return resource.read_text(encoding="utf-8").strip()

    def schemas(self) -> dict[str, Any]:
        return {"brief": intent_brief_schema(), "review": intent_review_schema()}

    def examples(self) -> dict[str, Any]:
        return intent_brief_examples()


def intent_brief_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant intent brief",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "adapter", "source_goal_digest", "brief"],
        "properties": {
            "version": {"const": 1},
            "adapter": {"const": "intent_brief"},
            "source_goal_digest": {"type": "string", "minLength": 1},
            "brief": {"type": "string", "minLength": 1},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "prompt"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                        "prompt": {"type": "string", "minLength": 1},
                        "answer": {"type": "string"},
                    },
                },
            },
        },
    }


def intent_review_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant exact-candidate intent review",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "version", "adapter", "source_goal_digest", "brief_digest",
            "candidate_tree", "verdict", "summary", "exceptions",
        ],
        "properties": {
            "version": {"const": 1},
            "adapter": {"const": "intent_brief"},
            "source_goal_digest": {"type": "string", "minLength": 1},
            "brief_digest": {"type": "string", "minLength": 1},
            "candidate_tree": {"type": "string", "minLength": 1},
            "verdict": {"enum": ["accepted", "rejected", "uncertain"]},
            "summary": {"type": "string", "minLength": 1},
            "exceptions": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
    }


def intent_brief_examples() -> dict[str, Any]:
    return {
        "brief": {
            "version": 1,
            "adapter": "intent_brief",
            "source_goal_digest": "<from task begin>",
            "brief": (
                "Import the supplied processor as ordinary monorepo-owned source. Preserve its "
                "behavior and integration, remove nested Git ownership, run relevant checks, and "
                "do not publish remotely."
            ),
            "questions": [],
        },
        "review": {
            "version": 1,
            "adapter": "intent_brief",
            "source_goal_digest": "<from task begin>",
            "brief_digest": "<from the stored brief artifact>",
            "candidate_tree": "<from task finish>",
            "verdict": "accepted",
            "summary": "The exact candidate satisfies the intent brief and collected checks pass.",
            "exceptions": [],
        },
    }
