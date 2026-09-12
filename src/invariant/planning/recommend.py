from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from invariant.errors import InvariantError
from invariant.governance.compiler import ObligationSet
from invariant.planning.frontier import frontier
from invariant.planning.model import Recommendation, Unit
from invariant.planning.validate import validate
from invariant.protocol import digest


Planner = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


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
    ) -> Recommendation:
        context = {
            "change": change,
            "base": base,
            "intent": intent,
            "scope": scope,
            "governance": governance,
            "obligations": obligations.as_dict(),
            "host_capacity": host_capacity,
        }
        proposal = self.planner(context) if self.planner else None
        raw_units = proposal.get("units") if isinstance(proposal, dict) else None
        if not isinstance(raw_units, list) or not raw_units:
            claims = [
                *scope.get("paths", []),
                *scope.get("interfaces", []),
                *scope.get("domains", []),
                *scope.get("contracts", []),
            ]
            raw_units = [{
                "id": "change",
                "objective": intent["statement"],
                "claims": claims or ["repo:."],
                "provides": [], "relies_on": [], "depends_on": [], "checks": [],
            }]
        try:
            units = tuple(Unit.parse(value, index) for index, value in enumerate(raw_units))
            conflicts = validate(units)
        except InvariantError:
            if proposal is None:
                raise
            units = (
                Unit("change", str(intent["statement"]), tuple(scope.get("paths", [])) or ("repo:.",)),
            )
            conflicts = ()
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
        return Recommendation.create(
            identifier=identifier,
            change=change,
            base=base,
            intent=str(intent["digest"]),
            units=units,
            conflicts=conflicts,
            maximum_parallelism=limit,
            recommended_frontier=selected,
            governance=governance.get("records", []),
        )
