"""Optional host integration for user-authenticated coding agents.

The harness is deliberately outside Invariant's mechanics and lifecycle
layers.  It consumes the public CLI protocol exactly like any other host.
"""

from invariant.harness.providers import AgentProvider, AgentResult, invoke

__all__ = ["AgentProvider", "AgentResult", "invoke"]
