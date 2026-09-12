"""One acceptance rule shared by the landing gate, the action store, and history validation."""

from __future__ import annotations

from typing import Any, Mapping

from invariant.protocol import ActionKind, is_direct_user_authority

REVIEW_KINDS = frozenset(
    {ActionKind.REVIEW_SEMANTICS.value, ActionKind.REVIEW_INDEPENDENT.value}
)
RESOLUTION_KINDS = frozenset(
    {
        ActionKind.RESOLVE_INTENT.value,
        ActionKind.ACCEPT_GOVERNANCE.value,
        ActionKind.SUPPLY_INTENT.value,
    }
)


def candidate_authors(state: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    attempts = state.get("attempts", {}).values()
    return (
        {str(item.get("actor")) for item in attempts},
        {str(item.get("principal")) for item in attempts},
    )


def independent_agent(actor: object, principal: object, state: Mapping[str, Any]) -> bool:
    """A delegated resolver must be an agent distinct from every candidate author."""

    if not isinstance(actor, str) or not actor.startswith("agent:"):
        return False
    authors, principals = candidate_authors(state)
    return actor not in authors and principal not in principals


def accepted_resolution(
    action: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    resolver: str,
    policy_change: bool = False,
) -> bool:
    """Whether one responded action satisfies a required resolution.

    Reviews never count: a review satisfies a review obligation only. Direct user authority
    satisfies every resolver. A delegated agent satisfies ``secondary-agent`` or
    ``any-attributable`` only when it is independent of the candidate's authors and the action
    was opened for that resolver. Policy changes always require direct user authority.
    """

    if action.get("kind") not in RESOLUTION_KINDS or action.get("status") != "responded":
        return False
    response = action.get("response")
    if not isinstance(response, Mapping) or response.get("resolution") != "accepted":
        return False
    actor = response.get("actor")
    principal = response.get("principal")
    if is_direct_user_authority(actor, principal):
        return True
    if policy_change or resolver == "user":
        return False
    if action.get("kind") == ActionKind.ACCEPT_GOVERNANCE.value and (
        action.get("resolver") != "secondary-agent"
    ):
        return False
    if resolver not in {"secondary-agent", "any-attributable"}:
        return False
    return independent_agent(actor, principal, state)
