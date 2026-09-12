from __future__ import annotations

from itertools import combinations
from typing import Iterable

from invariant.planning.model import Recommendation


def frontier(
    recommendation: Recommendation,
    *,
    converged: Iterable[str] = (),
    live: Iterable[str] = (),
    limit: int | None = None,
) -> tuple[str, ...]:
    done = set(converged)
    active = set(live)
    units = {unit.identifier: unit for unit in recommendation.units}
    ready = [
        unit.identifier
        for unit in recommendation.units
        if unit.identifier not in done
        and unit.identifier not in active
        and set(unit.depends_on) <= done
    ]
    conflicts = {tuple(pair) for pair in recommendation.conflicts}
    eligible = [
        identifier
        for identifier in ready
        if all(tuple(sorted((identifier, other))) not in conflicts for other in active)
    ]
    capacity = min(limit or recommendation.maximum_parallelism, recommendation.maximum_parallelism)
    for width in range(min(capacity, len(eligible)), 0, -1):
        for values in combinations(eligible, width):
            if all(tuple(sorted(pair)) not in conflicts for pair in combinations(values, 2)):
                return tuple(values)
    return ()
