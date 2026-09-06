from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import UsageError


@dataclass(frozen=True)
class CandidateReview:
    review_id: str
    candidate_tree: str
    verdict: str
    summary: str
    semantic_effect: str
    authority: str
    exceptions: list[str]

    @classmethod
    def load(cls, path: str | Path) -> "CandidateReview":
        source = Path(path)
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise UsageError(f"Invariant: no such file '{source}'") from None
        except yaml.YAMLError as exc:
            raise UsageError(f"Invariant: invalid YAML in {source}: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise UsageError("candidate review must be a version-1 mapping")
        allowed = {
            "version", "review_id", "candidate_tree", "verdict", "summary",
            "semantic_effect", "authority", "exceptions",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"candidate review has unknown field '{unknown[0]}'")

        def text(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value.strip():
                raise UsageError(f"candidate review {name} must be non-empty text")
            return value.strip()

        verdict = raw.get("verdict")
        if verdict not in {"accepted", "rejected", "uncertain"}:
            raise UsageError("candidate review verdict must be accepted, rejected, or uncertain")
        effect = text("semantic_effect")
        if effect not in {"no-record", "recorded"} and not effect.startswith("audit:"):
            raise UsageError(
                "candidate review semantic_effect must be no-record, recorded, or audit:<id>"
            )
        exceptions = raw.get("exceptions", [])
        if not isinstance(exceptions, list) or any(
            not isinstance(item, str) or not item.strip() for item in exceptions
        ):
            raise UsageError("candidate review exceptions must be a string list")
        return cls(
            text("review_id"),
            text("candidate_tree"),
            str(verdict),
            text("summary"),
            effect,
            text("authority"),
            sorted(set(exceptions)),
        )


def candidate_review_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Invariant semantic candidate review",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "version", "review_id", "candidate_tree", "verdict", "summary",
            "semantic_effect", "authority", "exceptions",
        ],
        "properties": {
            "version": {"const": 1},
            "review_id": {"type": "string", "minLength": 1},
            "candidate_tree": {"type": "string", "minLength": 1},
            "verdict": {"enum": ["accepted", "rejected", "uncertain"]},
            "summary": {"type": "string", "minLength": 1},
            "semantic_effect": {
                "type": "string",
                "pattern": "^(no-record|recorded|audit:[A-Za-z0-9][A-Za-z0-9._-]*)$",
            },
            "authority": {"type": "string", "minLength": 1},
            "exceptions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
