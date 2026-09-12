"""Optional host integration for user-authenticated coding agents.

The harness is deliberately outside Invariant's mechanics and lifecycle
layers. It consumes the private typed core protocol through the same internal
entry point as the human-facing host.
"""

from invariant.harness.providers import AgentProvider, AgentResult, invoke

__all__ = ["AgentProvider", "AgentResult", "invoke"]
