from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from invariant.protocol import CapabilityName, EnforcementPosture


@dataclass(frozen=True)
class Enforcement:
    posture: EnforcementPosture
    provider: str
    protected_resource: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "posture": self.posture.value,
            "provider": self.provider,
            "protected_resource": self.protected_resource,
            "evidence": list(self.evidence),
        }


class Uncontained:
    name = "uncontained"

    def evaluate(self, capability: CapabilityName, resource: str) -> Enforcement:
        posture = (
            EnforcementPosture.NOT_APPLICABLE
            if capability.capability_class.value == "resolution"
            else EnforcementPosture.ADVISORY
        )
        return Enforcement(posture, self.name, resource)
