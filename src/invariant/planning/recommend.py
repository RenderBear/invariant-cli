from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Mapping

from invariant.errors import InvariantError
from invariant.governance.compiler import ObligationSet
from invariant.planning.frontier import frontier
from invariant.planning.model import Recommendation, Unit
from invariant.planning.validate import validate
from invariant.protocol import digest


Planner = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


@dataclass(frozen=True)
class Rejection:
    code: str
    message: str
    proposal: Any


@dataclass(frozen=True)
class RecommendationResult:
    recommendation: Recommendation
    rejection: Rejection | None


class RecommendationService:
    def __init__(self, planner: Planner | None = None) -> None:
        self.planner = planner

    def recommend(
        self,
        *,
        change: str,
        base: str,
        intent: Mapping[str, Any],
        scope: Mapping[str, Any],
        governance: Mapping[str, Any],
        obligations: ObligationSet,
        policy_limit: int,
        host_capacity: int | None = None,
        planning: Mapping[str, Any] | None = None,
        proposal: Mapping[str, Any] | None = None,
        consult_planner: bool = True,
    ) -> RecommendationResult:
        context = {
            "change": change,
            "base": base,
            "intent": intent,
            "scope": scope,
            "governance": governance,
            "obligations": obligations.as_dict(),
            "host_capacity": host_capacity,
            "planning": dict(planning or {}),
        }
        if proposal is None and self.planner and consult_planner:
            proposal = self.planner(context)
        conservative = [{
            "id": "change",
            "objective": intent["statement"],
            "claims": [
                *scope.get("paths", []),
                *scope.get("interfaces", []),
                *scope.get("domains", []),
                *scope.get("contracts", []),
            ],
            "provides": [], "relies_on": [], "depends_on": [], "checks": [],
        }]
        rejection: Rejection | None = None
        raw_units = proposal.get("units") if isinstance(proposal, dict) else None
        if proposal is not None and (not isinstance(raw_units, list) or not raw_units):
            rejection = Rejection("invalid_recommendation", "proposal has no units", proposal)
            raw_units = conservative
        elif raw_units is None:
            raw_units = conservative
        try:
            units = tuple(Unit.parse(value, index) for index, value in enumerate(raw_units))
            conflicts = validate(units, obligations.serialize_on)
        except InvariantError as exc:
            if proposal is None:
                raise
            rejection = Rejection(exc.code, exc.message, proposal)
            units = tuple(Unit.parse(value, index) for index, value in enumerate(conservative))
            conflicts = validate(units, obligations.serialize_on)
        limit = min(policy_limit, obligations.parallel_limit or 32, host_capacity or 32, len(units))
        identifier = "rec-" + digest({"change": change, "base": base, "intent": intent["digest"], "units": [unit.as_dict() for unit in units]})[:16]
        provisional = Recommendation.create(
            identifier=identifier,
            change=change,
            base=base,
            intent=str(intent["digest"]),
            units=units,
            conflicts=conflicts,
            maximum_parallelism=limit,
            recommended_frontier=(),
            governance=governance.get("records", []),
        )
        selected = frontier(provisional, limit=limit)
        return RecommendationResult(
            Recommendation.create(
                identifier=identifier,
                change=change,
                base=base,
                intent=str(intent["digest"]),
                units=units,
                conflicts=conflicts,
                maximum_parallelism=limit,
                recommended_frontier=selected,
                governance=governance.get("records", []),
            ),
            rejection,
        )
