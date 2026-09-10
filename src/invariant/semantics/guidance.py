from __future__ import annotations

from importlib.resources import files

from invariant.protocol import TaskStage


def read(name: str) -> str:
    resource = files("invariant.semantics").joinpath("guidance", f"{name}.md")
    return resource.read_text(encoding="utf-8").strip()


def for_stage(stage: TaskStage | str, *, full: bool = False) -> str:
    stage = TaskStage.parse(stage)
    if not full:
        names = (
            ["brief"]
            if stage
            in {
                TaskStage.BRIEFING,
                TaskStage.AWAITING_BRANCH,
                TaskStage.BRIEFED,
            }
            else ["land"]
        )
        return "\n\n".join(read(name) for name in names)
    if stage == TaskStage.AWAITING_LANDING:
        names = ["semantic-reasoning", "repository-archaeology", "land", "human-ergonomics"]
    elif stage in {TaskStage.IMPLEMENTING, TaskStage.IMPLEMENTING_UNBORN}:
        names = [
            "brief",
            "semantic-reasoning",
            "repository-archaeology",
            "discovery",
            "coordinate",
            "land",
            "human-ergonomics",
        ]
    else:
        names = ["brief", "semantic-reasoning", "repository-archaeology", "human-ergonomics"]
    names.append("protocol-reference")
    return "\n\n".join(read(name) for name in names)
