from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


TASK_CREATED = "task.created"
CANDIDATE_EVIDENCED = "candidate.evidenced"


@dataclass(frozen=True)
class HookPhase:
    """Stable public contract for one semantic suspension point."""

    name: str
    occurs: str
    context: tuple[str, ...]
    may_block: bool


HOOK_PHASES = {
    TASK_CREATED: HookPhase(
        TASK_CREATED,
        "after the task receipt and work location are selected, before implementation",
        ("task", "goal", "goal_digest"),
        True,
    ),
    CANDIDATE_EVIDENCED: HookPhase(
        CANDIDATE_EVIDENCED,
        "after an exact candidate tree is built and mechanical evidence is collected, before landing",
        (
            "task",
            "goal_digest",
            "candidate_tree",
            "evidence",
            "retained_discoveries",
        ),
        True,
    ),
}


@dataclass(frozen=True)
class HookContext:
    task_root: Path
    task: str
    phase: str
    goal: str
    goal_digest: str
    candidate_tree: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    retained_discoveries: tuple[str, ...] = ()


@dataclass(frozen=True)
class HookRequest:
    id: str
    adapter: str
    phase: str
    kind: str
    prompt: str
    input_schema: dict[str, Any]
    schema_id: str = ""
    blocking: bool = True
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "adapter": self.adapter,
            "phase": self.phase,
            "kind": self.kind,
            "prompt": self.prompt,
            "input_schema": self.input_schema,
            "schema_id": self.schema_id or f"invariant://schemas/actions/{self.kind}/v1",
            "blocking": self.blocking,
            "context": self.context,
        }


@dataclass(frozen=True)
class HookResult:
    state: dict[str, Any]
    requests: tuple[HookRequest, ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()


class TaskAdapter(Protocol):
    """Optional semantic behavior around stable lifecycle phases.

    Adapters may request host judgment and persist private state, but they do
    not create branches, choose lifecycle stages, run landing, or update refs.
    """

    id: str

    def handle(
        self,
        context: HookContext,
        state: dict[str, Any] | None,
        source: str | None,
    ) -> HookResult: ...

    def context(self, task_root: Path, state: dict[str, Any]) -> list[str]: ...

    def guidance(self, phase: str) -> str: ...

    def schemas(self) -> dict[str, Any]: ...

    def examples(self) -> dict[str, Any]: ...
