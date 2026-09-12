"""Repository-bound in-process MCP gateway for protocol v1."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any
import uuid

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from invariant import __version__
from invariant.application import InvariantApplication, OperationResult
from invariant.errors import InvariantError
from invariant.harness.identity import UNAUTHENTICATED
from invariant.protocol import Outcome, PROTOCOL_VERSION


Envelope = dict[str, Any]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
EXTERNAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def _operation(value: str | None) -> str:
    return value or f"op-{uuid.uuid4().hex}"


def _error(command: str, error: InvariantError) -> Envelope:
    outcome = Outcome.BLOCKED if error.exit_code == 1 else Outcome.FAILED
    return {
        "protocol": PROTOCOL_VERSION,
        "command": command,
        "status": "blocked" if error.exit_code == 1 else "error",
        "outcome": outcome.value,
        "result": error.data or {},
        "diagnostics": [{"code": error.code, "message": error.message}],
    }


def create_server(
    repository: str = ".",
    *,
    principal: str = "harness:mcp",
) -> MCPServer:
    # MCP is never an authenticated user transport; a user: principal is refused at bind time.
    app = InvariantApplication.bind(
        repository, principal=principal, authentication=UNAUTHENTICATED
    )
    server = MCPServer(
        "invariant",
        title="Invariant",
        description="Semantic kernel and Git-grounded lifecycle for governed agentic work.",
        instructions=(
            f"This gateway is bound to {app.repository.primary_worktree}. Supplied intent, "
            "resolution authority, and execution capability are distinct. Open a durable "
            "change, use only its current recommendation and grants, and treat denied, stale, "
            "or needs_input as protocol results rather than permission to bypass the lifecycle."
        ),
        version=__version__,
    )

    def call(command: str, operation: Callable[[], OperationResult]) -> Envelope:
        try:
            return operation().envelope(command)
        except InvariantError as exc:
            return _error(command, exc)

    @server.tool(title="Validate governed state", annotations=READ_ONLY)
    def invariant_state_validate() -> Envelope:
        """Validate policy, records, ledgers, refs, and attestations."""
        return call("state.validate", app.state_validate)

    @server.tool(title="Compile governance context", annotations=READ_ONLY)
    def invariant_governance_context(
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
        contracts: list[str] | None = None,
        capability: str | None = None,
        at: str | None = None,
    ) -> Envelope:
        """Select accepted meaning and compile its closed consequences."""
        return call(
            "governance.context",
            lambda: app.governance_context(
                paths=paths or [],
                interfaces=interfaces or [],
                domains=domains or [],
                contracts=contracts or [],
                capability=capability,
                at=at,
            ),
        )

    @server.tool(title="Open durable change", annotations=MUTATION)
    def invariant_change_open(
        change_id: str,
        intent: str,
        supplier: str,
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
        contracts: list[str] | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Bind attributable supplied intent, exact base, and governance in Git."""
        return call(
            "change.open",
            lambda: app.change_open(
                change_id,
                intent=intent,
                supplier=supplier,
                paths=paths or [],
                interfaces=interfaces or [],
                domains=domains or [],
                contracts=contracts or [],
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Recommend work shape", annotations=MUTATION)
    def invariant_change_recommend(
        change_id: str,
        host_capacity: int | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Record Invariant's conservative or semantic work recommendation."""
        return call(
            "change.recommend",
            lambda: app.change_recommend(
                change_id,
                host_capacity=host_capacity,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Inspect durable change", annotations=READ_ONLY)
    def invariant_change_inspect(change_id: str) -> Envelope:
        """Return reduced state, frontier, pending actions, and redacted grants."""
        return call("change.inspect", lambda: app.change_inspect(change_id))

    @server.tool(title="Create handoff capsule", annotations=READ_ONLY)
    def invariant_change_handoff(change_id: str) -> Envelope:
        """Return a canonical token-free capsule sufficient for another harness."""
        return call("change.handoff", lambda: app.change_handoff(change_id))

    @server.tool(title="Resume handed-off change", annotations=MUTATION)
    def invariant_change_resume(
        capsule: dict[str, Any],
        operation_id: str | None = None,
    ) -> Envelope:
        """Validate causal state and revoke bearer grants absent from the handoff."""
        return call(
            "change.resume",
            lambda: app.change_resume(
                capsule,
                actor=principal,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Inspect semantic action", annotations=READ_ONLY)
    def invariant_action_inspect(change_id: str, action_id: str) -> Envelope:
        """Expand one intent-bound action and its response schema."""
        return call(
            "action.inspect",
            lambda: app.action_inspect(change_id, action_id),
        )

    @server.tool(title="Respond to semantic action", annotations=MUTATION)
    def invariant_action_respond(
        change_id: str,
        action_id: str,
        response: dict[str, Any],
        actor: str,
        resolution_token: str | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume intent.resolve for delegated responses; direct user intent needs no token."""
        return call(
            "action.respond",
            lambda: app.action_respond(
                change_id,
                action_id,
                response=response,
                actor=actor,
                token=resolution_token,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Request scoped capability", annotations=MUTATION)
    def invariant_capability_request(
        change_id: str,
        capability: str,
        actor: str,
        resource: str,
        unit: str | None = None,
        attempt: str | None = None,
        reason: str | None = None,
        expected_ledger: str | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Decide and record one resolution or execution capability request."""
        return call(
            "capability.request",
            lambda: app.capability_request(
                change_id,
                capability=capability,
                actor=actor,
                resource=resource,
                unit=unit,
                attempt=attempt,
                reason=reason,
                expected_ledger=expected_ledger,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Inspect decision or grant", annotations=READ_ONLY)
    def invariant_capability_inspect(change_id: str, identifier: str) -> Envelope:
        """Inspect a durable decision or redacted grant; tokens are never returned."""
        return call(
            "capability.inspect",
            lambda: app.capability_inspect(change_id, identifier),
        )

    @server.tool(title="Revoke live grant", annotations=MUTATION)
    def invariant_capability_revoke(
        change_id: str,
        grant_id: str,
        reason: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Revoke a current grant without erasing its attribution."""
        return call(
            "capability.revoke",
            lambda: app.capability_revoke(
                change_id,
                grant_id,
                actor=principal,
                reason=reason,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Create isolated attempt", annotations=MUTATION)
    def invariant_work_create(
        change_id: str,
        unit_id: str,
        attempt_id: str,
        actor: str,
        grant_token: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume worktree.create and materialize one frontier attempt."""
        return call(
            "work.create",
            lambda: app.work_create(
                change_id,
                unit_id=unit_id,
                attempt_id=attempt_id,
                actor=actor,
                token=grant_token,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Submit exact work result", annotations=MUTATION)
    def invariant_work_submit(
        change_id: str,
        attempt_id: str,
        actor: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Record one clean committed result and audit its actual path reach."""
        return call(
            "work.submit",
            lambda: app.work_submit(
                change_id,
                attempt_id=attempt_id,
                actor=actor,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Discard retained work", annotations=DESTRUCTIVE)
    def invariant_work_discard(
        change_id: str,
        refs: list[str],
        grant_token: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume work.discard for exact refs after direct user authority."""
        return call(
            "work.discard",
            lambda: app.work_discard(
                change_id,
                refs=refs,
                token=grant_token,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Converge submitted unit", annotations=MUTATION)
    def invariant_candidate_converge(
        change_id: str,
        attempt_id: str,
        grant_token: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume candidate.converge and compare-and-swap the aggregate candidate."""
        return call(
            "candidate.converge",
            lambda: app.candidate_converge(
                change_id,
                attempt_id=attempt_id,
                token=grant_token,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Capture candidate evidence", annotations=MUTATION)
    def invariant_candidate_evidence(
        change_id: str,
        verifier_tokens: dict[str, str] | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume exact verifier grants and open any required resolution action."""
        return call(
            "candidate.evidence",
            lambda: app.candidate_evidence(
                change_id,
                tokens=verifier_tokens or {},
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Land exact candidate", annotations=MUTATION)
    def invariant_integration_land(
        change_id: str,
        grant_token: str,
        subject: str | None = None,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume integration.land and atomically move the local integration ref."""
        return call(
            "integration.land",
            lambda: app.integration_land(
                change_id,
                token=grant_token,
                subject=subject,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Reconcile interrupted landing", annotations=MUTATION)
    def invariant_integration_reconcile(
        change_id: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Finish bookkeeping only when Git proves the recorded transaction outcome."""
        return call(
            "integration.reconcile",
            lambda: app.integration_reconcile(
                change_id, operation_id=_operation(operation_id)
            ),
        )

    @server.tool(title="Publish exact landing", annotations=EXTERNAL)
    def invariant_publication_publish(
        change_id: str,
        grant_token: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Consume remote.publish for the exact local landing and configured upstream."""
        return call(
            "publication.publish",
            lambda: app.publication_publish(
                change_id,
                token=grant_token,
                operation_id=_operation(operation_id),
            ),
        )

    @server.tool(title="Invalidate change", annotations=MUTATION)
    def invariant_change_invalidate(
        change_id: str,
        reason: str,
        actor: str,
        grant_token: str,
        operation_id: str | None = None,
    ) -> Envelope:
        """Stop future work without deleting ledger, refs, or worktrees."""
        return call(
            "change.invalidate",
            lambda: app.change_invalidate(
                change_id,
                reason=reason,
                actor=actor,
                token=grant_token,
                operation_id=_operation(operation_id),
            ),
        )

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invariant-mcp",
        description="Run the Invariant governance protocol as a repository-bound MCP server.",
    )
    parser.add_argument("--repository", default=".")
    parser.add_argument("--principal", default="harness:mcp")
    parser.add_argument(
        "--version", action="version", version=f"invariant-mcp {__version__}"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        server = create_server(args.repository, principal=args.principal)
    except InvariantError as exc:
        build_parser().exit(exc.exit_code, f"{exc.message}\n")
    server.run()


if __name__ == "__main__":
    main()
