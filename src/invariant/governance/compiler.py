from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from invariant.governance.records import Directive
from invariant.governance.selection import GovernanceSelection
from invariant.mechanics.config import Config
from invariant.protocol import CapabilityName, DirectiveKind, Scope, digest


@dataclass(frozen=True)
class ObligationSet:
    sources: tuple[str, ...]
    selected_context: tuple[str, ...]
    denied_capabilities: Mapping[str, tuple[str, ...]]
    required_resolution: Mapping[str, str]
    required_reviews: tuple[str, ...]
    required_verifiers: tuple[str, ...]
    serialize_on: tuple[str, ...]
    parallel_limit: int | None
    containment: Mapping[str, str]
    blocks: tuple[str, ...]
    digest: str

    def denied_by(self, capability: CapabilityName) -> tuple[str, ...]:
        return self.denied_capabilities.get(capability.value, ())

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "selected_context": list(self.selected_context),
            "denied_capabilities": {
                name: list(sources) for name, sources in self.denied_capabilities.items()
            },
            "required_resolution": dict(self.required_resolution),
            "required_reviews": list(self.required_reviews),
            "required_verifiers": list(self.required_verifiers),
            "serialize_on": list(self.serialize_on),
            "parallel_limit": self.parallel_limit,
            "containment": dict(self.containment),
            "blocks": list(self.blocks),
            "digest": self.digest,
        }


def compile_obligations(
    config: Config,
    selection: GovernanceSelection,
    scope: Scope | None = None,
) -> ObligationSet:
    sources = {record.reference for record in selection.records}
    denied: dict[str, set[str]] = {}
    resolution: dict[str, str] = {}
    reviews: set[str] = set()
    verifiers: set[str] = set()
    serialization: set[str] = set()
    containment: dict[str, str] = {}
    parallel = None if config.parallelism.maximum == "auto" else int(config.parallelism.maximum)
    blocks: set[str] = set()

    if config.publication == "off":
        denied.setdefault(CapabilityName.REMOTE_PUBLISH.value, set()).add("policy:publication")
        sources.add("policy:publication")
    if parallel is not None:
        sources.add("policy:parallelism.maximum")

    if scope and _changes_governance(scope, selection):
        resolution[CapabilityName.INTEGRATION_LAND.value] = "user"
        sources.add("protocol:governance-acceptance")

    strength = {"any-attributable": 0, "agent": 1, "user": 2}
    for record in selection.records:
        verifiers.update(record.strings("verifies"))
        if record.strings("verifies"):
            sources.add(record.reference)
        if record.kind == "semantic":
            reviews.add("attributable")
        elif record.kind == "contract":
            reviews.add("independent")
        for directive in record.directives:
            source = record.reference
            values = directive.values
            if directive.kind is DirectiveKind.DENY_CAPABILITY:
                denied.setdefault(str(values["capability"]), set()).add(source)
            elif directive.kind is DirectiveKind.REQUIRE_RESOLUTION:
                name = str(values["capability"])
                resolver = str(values["resolver"])
                current = resolution.get(name)
                if current is None or strength[resolver] > strength[current]:
                    resolution[name] = resolver
            elif directive.kind is DirectiveKind.REQUIRE_REVIEW:
                reviews.add(str(values["mode"]))
            elif directive.kind is DirectiveKind.REQUIRE_VERIFIER:
                verifiers.add(str(values["locator"]))
            elif directive.kind is DirectiveKind.SERIALIZE:
                serialization.update(str(item) for item in values["on"])
            elif directive.kind is DirectiveKind.LIMIT_PARALLELISM:
                value = int(values["maximum"])
                parallel = value if parallel is None else min(parallel, value)
            elif directive.kind is DirectiveKind.REQUIRE_CONTAINMENT:
                containment[str(values["capability"])] = str(values["enforcement"])

    if "independent" in reviews:
        reviews.discard("attributable")
    body = {
        "sources": sorted(sources),
        "selected_context": sorted(
            f"{record.kind}:{record.identifier}"
            for record in selection.records
            if record.kind in {"semantic", "domain"}
        ),
        "denied_capabilities": {name: sorted(value) for name, value in sorted(denied.items())},
        "required_resolution": dict(sorted(resolution.items())),
        "required_reviews": sorted(reviews),
        "required_verifiers": sorted(verifiers),
        "serialize_on": sorted(serialization),
        "parallel_limit": parallel,
        "containment": dict(sorted(containment.items())),
        "blocks": sorted(blocks),
    }
    return ObligationSet(
        tuple(body["sources"]),
        tuple(body["selected_context"]),
        {name: tuple(value) for name, value in body["denied_capabilities"].items()},
        body["required_resolution"],
        tuple(body["required_reviews"]),
        tuple(body["required_verifiers"]),
        tuple(body["serialize_on"]),
        parallel,
        body["containment"],
        tuple(body["blocks"]),
        digest(body),
    )


def _changes_governance(scope: Scope, selection: GovernanceSelection) -> bool:
    paths = tuple(path.removeprefix("repo:") for path in scope.paths)
    if any(
        path == ".invariant/config.yml"
        or path.startswith(".invariant/records/")
        for path in paths
    ):
        return True
    canonical: set[str] = set()
    for record in selection.records:
        values = [*record.strings("architecture")]
        document = record.data.get("document")
        if isinstance(document, str):
            values.append(document)
        values.extend(
            item
            for item in record.strings("material")
            if item.startswith("architecture:")
        )
        for locator in values:
            value = locator.removeprefix("architecture:")
            path, separator, _ = value.rpartition("#")
            if separator:
                canonical.add(path.removeprefix("repo:").strip("/"))
    return any(
        path == governed
        or path.startswith(governed + "/")
        or governed.startswith(path + "/")
        for path in paths
        for governed in canonical
    )
