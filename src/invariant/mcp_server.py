from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from invariant import __version__
from invariant.errors import InvariantError
from invariant.mechanics import git


Envelope = dict[str, Any]

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
SAFE_MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
LANDING_MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
DESTRUCTIVE_MUTATION = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


@dataclass(frozen=True)
class CoreClient:
    """Invoke the versioned core command contract without sharing process state."""

    repository: Path

    def call(self, command: str, *arguments: str) -> Envelope:
        completed = subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "invariant.cli.app",
                "--format",
                "json",
                *arguments,
            ],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            detail = (completed.stderr or completed.stdout).strip()
            return _transport_error(
                command,
                "invalid_protocol_output",
                "Invariant returned invalid JSON"
                + (f": {detail}" if detail else ""),
            )
        if not isinstance(payload, dict):
            return _transport_error(
                command,
                "invalid_protocol_output",
                "Invariant returned a non-object response",
            )
        if payload.get("protocol") != 1:
            return _transport_error(
                command,
                "unsupported_protocol",
                f"Invariant returned unsupported protocol {payload.get('protocol')!r}",
            )
        if payload.get("command") != command:
            return _transport_error(
                command,
                "invalid_protocol_output",
                f"Invariant returned command {payload.get('command')!r}, expected {command!r}",
            )
        if (
            not isinstance(payload.get("status"), str)
            or not isinstance(payload.get("outcome"), str)
            or not isinstance(payload.get("result"), (dict, list))
            or not isinstance(payload.get("diagnostics"), list)
        ):
            return _transport_error(
                command,
                "invalid_protocol_output",
                "Invariant returned an incomplete protocol envelope",
            )
        return payload


def _transport_error(command: str, code: str, message: str) -> Envelope:
    return {
        "protocol": 1,
        "command": command,
        "status": "error",
        "outcome": "failed",
        "result": {},
        "diagnostics": [{"code": code, "message": message}],
    }


def _option(arguments: list[str], name: str, value: str | None) -> None:
    if value is not None:
        arguments.extend([name, value])


def _values(arguments: list[str], name: str, values: list[str] | None) -> None:
    for value in values or []:
        arguments.extend([name, value])


def create_server(repository: Path | str = ".") -> MCPServer:
    """Create one stdio MCP server bound to one Git repository kernel."""

    resolved = git.root(repository)
    primary = git.primary_worktree(resolved).resolve()
    client = CoreClient(primary)
    server = MCPServer(
        "invariant",
        title="Invariant",
        description="Durable semantic and repository-safety kernel for agentic changes.",
        instructions=(
            f"This server is bound to {primary}. Use semantic context and reach before "
            "implementation. Begin every managed write as a task, work only in the returned "
            "worktree, and finish through Invariant. A blocked or needs_input outcome is a valid "
            "protocol result, not permission to bypass the lifecycle."
        ),
        version=__version__,
    )

    @server.tool(title="Inspect Invariant repository", annotations=READ_ONLY)
    def invariant_status(task_id: str | None = None) -> Envelope:
        """Inspect repository policy and active work, or retrieve one durable task status."""

        if task_id:
            return client.call("task.status", "task", "status", task_id)
        return client.call("status", "status")

    @server.tool(title="Validate Invariant state", annotations=READ_ONLY)
    def invariant_validate(landing: bool = False) -> Envelope:
        """Validate tracked semantic state; optionally apply landing-history checks."""

        arguments = ["state", "validate"]
        if landing:
            arguments.append("--landing")
        return client.call("state.validate", *arguments)

    @server.tool(title="Retrieve accepted semantics", annotations=READ_ONLY)
    def invariant_semantics(
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
        at: str | None = None,
    ) -> Envelope:
        """Retrieve accepted semantic records by path, interface, or responsibility domain."""

        arguments = ["context", "semantics"]
        _values(arguments, "--path", paths)
        _values(arguments, "--interface", interfaces)
        _values(arguments, "--domain", domains)
        _option(arguments, "--at", at)
        return client.call("context.semantics", *arguments)

    @server.tool(title="Retrieve responsibility context", annotations=READ_ONLY)
    def invariant_context(domains: list[str]) -> Envelope:
        """Retrieve selected domains with their records, contracts, and constraints."""

        return client.call("context.rows", "context", "rows", *domains)

    @server.tool(title="Compute change reach", annotations=READ_ONLY)
    def invariant_reach(
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
        base: str | None = None,
        history: bool = False,
        root: bool = False,
    ) -> Envelope:
        """Compute semantic reach, affected records, governance, and applicable topology."""

        arguments = ["context", "reach"]
        _values(arguments, "--path", paths)
        _values(arguments, "--interface", interfaces)
        _values(arguments, "--domain", domains)
        _option(arguments, "--base", base)
        if history:
            arguments.append("--history")
        if root:
            arguments.append("--root")
        return client.call("context.reach", *arguments)

    @server.tool(title="Begin managed change", annotations=SAFE_MUTATION)
    def invariant_task_begin(
        task_id: str,
        goal: str,
        boundary: str = "unresolved",
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
        intent_brief: bool | None = None,
    ) -> Envelope:
        """Create or resume isolated work for one change and return its worktree and actions."""

        arguments = ["task", "begin", task_id, "--goal", goal, "--boundary", boundary]
        _values(arguments, "--path", paths)
        _values(arguments, "--interface", interfaces)
        _values(arguments, "--domain", domains)
        if intent_brief is not None:
            arguments.append("--intent-brief" if intent_brief else "--no-intent-brief")
        return client.call("task.begin", *arguments)

    @server.tool(title="Read task guidance", annotations=READ_ONLY)
    def invariant_task_guidance(task_id: str, full: bool = False) -> Envelope:
        """Compile accepted semantics and stage guidance for an active managed change."""

        arguments = ["task", "guidance", task_id]
        if full:
            arguments.append("--full")
        return client.call("task.guidance", *arguments)

    @server.tool(title="Check resumable task", annotations=SAFE_MUTATION)
    def invariant_task_check(
        task_id: str,
        goal: str,
        compatible_goal: bool = False,
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        domains: list[str] | None = None,
    ) -> Envelope:
        """Check receipt freshness before resuming; optionally attest compatible goal wording."""

        arguments = ["task", "check", task_id, "--goal", goal]
        if compatible_goal:
            arguments.append("--compatible-goal")
        _values(arguments, "--path", paths)
        _values(arguments, "--interface", interfaces)
        _values(arguments, "--domain", domains)
        return client.call("task.check", *arguments)

    @server.tool(title="Read pending task action", annotations=READ_ONLY)
    def invariant_task_action(task_id: str, action_id: str) -> Envelope:
        """Retrieve one pending semantic action with its exact context and response schema."""

        return client.call("task.action", "task", "action", task_id, action_id)

    @server.tool(title="Respond to task action", annotations=LANDING_MUTATION)
    def invariant_task_respond(
        task_id: str, action_id: str, response: dict[str, Any]
    ) -> Envelope:
        """Submit one schema-bound response; authority and candidate bindings are revalidated."""

        with tempfile.TemporaryDirectory(prefix="invariant-mcp-response-") as directory:
            source = Path(directory) / "response.json"
            source.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            return client.call(
                "task.respond",
                "task",
                "respond",
                task_id,
                action_id,
                "--input",
                str(source),
            )

    @server.tool(title="Finish managed change", annotations=LANDING_MUTATION)
    def invariant_task_finish(
        task_id: str,
        subject: str | None = None,
        checks: list[str] | None = None,
    ) -> Envelope:
        """Evidence and review the exact candidate, then land it only when every gate passes."""

        arguments = ["task", "finish", task_id]
        _option(arguments, "--subject", subject)
        _values(arguments, "--check", checks)
        return client.call("task.finish", *arguments)

    @server.tool(title="Continue approved task", annotations=LANDING_MUTATION)
    def invariant_task_continue(task_id: str, apply: bool = False) -> Envelope:
        """Inspect or apply the next assisted lifecycle transition, including atomic landing."""

        arguments = ["task", "continue", task_id]
        if apply:
            arguments.append("--apply")
        return client.call("task.continue", *arguments)

    @server.tool(title="Reconcile completed landing", annotations=SAFE_MUTATION)
    def invariant_task_reconcile(task_id: str) -> Envelope:
        """Repair task bookkeeping when a verified landing completed before archival did."""

        return client.call("task.reconcile", "task", "reconcile", task_id)

    @server.tool(title="Inspect task evidence", annotations=READ_ONLY)
    def invariant_task_evidence(
        task_id: str, evidence_id: str | None = None
    ) -> Envelope:
        """List candidate-bound evidence or retrieve one complete evidence record."""

        arguments = ["task", "evidence", task_id]
        if evidence_id:
            arguments.append(evidence_id)
        return client.call("task.evidence", *arguments)

    @server.tool(title="Validate parallel plan", annotations=READ_ONLY)
    def invariant_plan_validate(plan: dict[str, Any]) -> Envelope:
        """Validate dependencies, contract causality, claims, and governing digests before dispatch."""

        identifier = plan.get("id")
        filename = (
            f"{identifier}.yml"
            if isinstance(identifier, str) and git.valid_id(identifier)
            else "invalid-plan.yml"
        )
        with tempfile.TemporaryDirectory(prefix="invariant-mcp-plan-") as directory:
            source = Path(directory) / filename
            source.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            return client.call(
                "coordinate.plan.validate",
                "coordinate",
                "plan",
                "validate",
                str(source),
            )

    @server.tool(title="Acquire parallel work lease", annotations=SAFE_MUTATION)
    def invariant_lease_acquire(
        unit: str,
        paths: list[str] | None = None,
        interfaces: list[str] | None = None,
        governance: list[str] | None = None,
        domains: list[str] | None = None,
        governing_digest: str | None = None,
        task_id: str | None = None,
        owner: str | None = None,
        duration: str = "2h",
    ) -> Envelope:
        """Claim non-overlapping paths, interfaces, or governance for one parallel unit."""

        arguments = ["coordinate", "lease", "acquire", unit, "--duration", duration]
        _values(arguments, "--path", paths)
        _values(arguments, "--interface", interfaces)
        _values(arguments, "--governance", governance)
        _values(arguments, "--domain", domains)
        _option(arguments, "--digest", governing_digest)
        _option(arguments, "--task", task_id)
        _option(arguments, "--owner", owner)
        return client.call("coordinate.lease.acquire", *arguments)

    @server.tool(title="Inspect parallel work leases", annotations=READ_ONLY)
    def invariant_lease_status(
        unit: str | None = None,
        scope: str | None = None,
        domain: str | None = None,
    ) -> Envelope:
        """List live leases, or verify that one unit remains fresh against landed work."""

        if unit:
            return client.call(
                "coordinate.lease.fresh", "coordinate", "lease", "fresh", unit
            )
        arguments = ["coordinate", "lease", "list"]
        _option(arguments, "--scope", scope)
        _option(arguments, "--domain", domain)
        return client.call("coordinate.lease.list", *arguments)

    @server.tool(title="Renew parallel work lease", annotations=SAFE_MUTATION)
    def invariant_lease_renew(unit: str, duration: str = "2h") -> Envelope:
        """Extend one existing lease while refreshing its causal branch tip."""

        return client.call(
            "coordinate.lease.renew",
            "coordinate",
            "lease",
            "renew",
            unit,
            "--duration",
            duration,
        )

    @server.tool(title="Release parallel work lease", annotations=DESTRUCTIVE_MUTATION)
    def invariant_lease_release(unit: str) -> Envelope:
        """Release one parallel ownership claim after completion or explicit abandonment."""

        return client.call(
            "coordinate.lease.release", "coordinate", "lease", "release", unit
        )

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invariant-mcp",
        description="Run the Invariant semantic kernel as a repository-bound MCP server.",
    )
    parser.add_argument(
        "--repository",
        default=".",
        help="path inside the one Git repository this server may operate on",
    )
    parser.add_argument("--version", action="version", version=f"invariant-mcp {__version__}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        server = create_server(args.repository)
    except InvariantError as exc:
        build_parser().exit(exc.exit_code, f"{exc.message}\n")
    server.run()


if __name__ == "__main__":
    main()
