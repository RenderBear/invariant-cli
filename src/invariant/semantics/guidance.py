from __future__ import annotations

from importlib.resources import files


def read(name: str) -> str:
    resource = files("invariant.semantics").joinpath("guidance", f"{name}.md")
    return resource.read_text(encoding="utf-8").strip()


def agent_workflow() -> str:
    return read("bootstrap")


def for_stage(stage: str, *, full: bool = False) -> str:
    if not full:
        names = (
            ["land", "human-ergonomics"]
            if stage in {"awaiting-review", "awaiting-landing"}
            else ["brief", "human-ergonomics"]
            if stage in {"briefing", "awaiting-branch"}
            else ["brief", "land", "human-ergonomics"]
        )
        return "\n\n".join(read(name) for name in names)
    if stage == "awaiting-landing":
        names = ["semantic-reasoning", "repository-archaeology", "land", "human-ergonomics"]
    elif stage in {"implementing", "implementing-unborn"}:
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
