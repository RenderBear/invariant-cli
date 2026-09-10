from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from invariant.errors import UsageError


def _load(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"Invariant: no such file '{source}'") from None
    except yaml.YAMLError as exc:
        raise UsageError(f"Invariant: invalid YAML in {source}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise UsageError(f"{label} must be a version-1 YAML mapping")
    return raw


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"{label} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class BriefQuestion:
    identifier: str
    prompt: str
    answer: str = ""

    @classmethod
    def parse(cls, value: Any, index: int) -> "BriefQuestion":
        label = f"intent brief questions[{index}]"
        if not isinstance(value, dict):
            raise UsageError(f"{label} must be a mapping")
        unknown = sorted(set(value) - {"id", "prompt", "answer"})
        if unknown:
            raise UsageError(f"{label} has unknown field '{unknown[0]}'")
        identifier = _text(value.get("id"), f"{label}.id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
            raise UsageError(f"{label}.id is invalid")
        answer = value.get("answer", "")
        if not isinstance(answer, str):
            raise UsageError(f"{label}.answer must be text")
        return cls(identifier, _text(value.get("prompt"), f"{label}.prompt"), answer.strip())


@dataclass(frozen=True)
class IntentBrief:
    source_goal_digest: str
    brief: str
    questions: list[BriefQuestion] = field(default_factory=list)

    @property
    def unanswered(self) -> list[BriefQuestion]:
        return [question for question in self.questions if not question.answer]

    @classmethod
    def load(cls, path: str | Path) -> "IntentBrief":
        raw = _load(path, "intent brief")
        allowed = {"version", "adapter", "source_goal_digest", "brief", "questions"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"intent brief has unknown field '{unknown[0]}'")
        if raw.get("adapter") != "intent_brief":
            raise UsageError("intent brief requires adapter: intent_brief")
        questions = raw.get("questions", [])
        if not isinstance(questions, list):
            raise UsageError("intent brief questions must be a list")
        parsed = [BriefQuestion.parse(value, index) for index, value in enumerate(questions)]
        identifiers = [item.identifier for item in parsed]
        if len(identifiers) != len(set(identifiers)):
            raise UsageError("intent brief question ids must be unique")
        return cls(
            _text(raw.get("source_goal_digest"), "intent brief source_goal_digest"),
            _text(raw.get("brief"), "intent brief prose"),
            parsed,
        )


@dataclass(frozen=True)
class IntentReview:
    source_goal_digest: str
    brief_digest: str
    candidate_tree: str
    verdict: str
    summary: str
    candidate_defects: list[str]
    retained_discoveries: list[str]

    @property
    def exceptions(self) -> list[str]:
        """Compatibility alias for the former ambiguous field name."""

        return self.candidate_defects

    @classmethod
    def load(cls, path: str | Path) -> "IntentReview":
        raw = _load(path, "intent review")
        allowed = {
            "version",
            "adapter",
            "source_goal_digest",
            "brief_digest",
            "candidate_tree",
            "verdict",
            "summary",
            "exceptions",
            "candidate_defects",
            "retained_discoveries",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise UsageError(f"intent review has unknown field '{unknown[0]}'")
        if raw.get("adapter") != "intent_brief":
            raise UsageError("intent review requires adapter: intent_brief")
        verdict = raw.get("verdict")
        if verdict not in {"accepted", "rejected", "uncertain"}:
            raise UsageError("intent review verdict must be accepted, rejected, or uncertain")
        if "exceptions" in raw and "candidate_defects" in raw:
            raise UsageError(
                "intent review must use candidate_defects or legacy exceptions, not both"
            )
        defects = raw.get("candidate_defects", raw.get("exceptions", []))
        if not isinstance(defects, list) or any(
            not isinstance(item, str) or not item.strip() for item in defects
        ):
            raise UsageError("intent review candidate_defects must be a string list")
        retained = raw.get("retained_discoveries", [])
        if not isinstance(retained, list) or any(
            not isinstance(item, str) or not item.startswith("discovery:")
            for item in retained
        ):
            raise UsageError(
                "intent review retained_discoveries must use discovery:<id> references"
            )
        return cls(
            _text(raw.get("source_goal_digest"), "intent review source_goal_digest"),
            _text(raw.get("brief_digest"), "intent review brief_digest"),
            _text(raw.get("candidate_tree"), "intent review candidate_tree"),
            str(verdict),
            _text(raw.get("summary"), "intent review summary"),
            sorted(set(defects)),
            sorted(set(retained)),
        )
