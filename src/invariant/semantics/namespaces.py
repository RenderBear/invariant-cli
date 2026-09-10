from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from invariant.errors import UsageError


_NAMESPACE = re.compile(r"[a-z][a-z0-9-]*")
_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
SOURCE_SCOPE_NAMESPACES = frozenset({"domain", "contract"})


@dataclass(frozen=True)
class Locator:
    """One canonical semantic coordinate.

    The first colon identifies the object kind.  The identifier is deliberately
    narrower than legacy task IDs because semantic coordinates are durable and
    user-facing across tools.
    """

    namespace: str
    identifier: str

    @property
    def value(self) -> str:
        return f"{self.namespace}:{self.identifier}"


def valid_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(value))


def parse_locator(value: str, *, allowed: Iterable[str] | None = None) -> Locator:
    namespace, separator, identifier = value.partition(":")
    allowed_set = set(allowed) if allowed is not None else None
    if (
        not separator
        or not _NAMESPACE.fullmatch(namespace)
        or not valid_identifier(identifier)
    ):
        raise UsageError(
            "Invariant: scope must use a lowercase namespace and stable id, "
            "such as domain:backend or contract:payments-api"
        )
    if allowed_set is not None and namespace not in allowed_set:
        choices = " or ".join(f"{item}:<id>" for item in sorted(allowed_set))
        raise UsageError(f"Invariant: source scope must use {choices}")
    return Locator(namespace, identifier)


def parse_source_scope(value: str) -> Locator:
    return parse_locator(value, allowed=SOURCE_SCOPE_NAMESPACES)
