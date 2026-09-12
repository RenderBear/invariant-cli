# Invariant CLI and MCP basics

The CLI is the operator and recovery surface. The repository-bound MCP server is the harness
surface. Both call the same in-process `InvariantApplication`; Git-backed state is authoritative.

## Initialize and inspect

```bash
invariant init --defaults
invariant status
invariant governance explain --path src/payments
```

Initialization writes version-two policy only. Commit it before opening a change.

The tracked settings are:

```bash
invariant set authority.intent.suppliers user
invariant set authority.resolution.delegation agent
invariant set execution.transitions auto
invariant set integration_branch main
invariant set publication off
invariant set parallelism.maximum 4
```

Intent supply and resolution delegation are authority policy. `execution.transitions` is a hint
for compound host UX only; the low-level CLI remains explicit. It grants no semantic authority.

## Open a change

```bash
invariant change open change-id \
  --intent "Desired repository outcome" \
  --supplier user:alice \
  --path src/service

invariant change recommend change-id
invariant change inspect change-id
invariant change handoff change-id
```

The ledger is durable under `refs/invariant/changes/change-id`. The recommendation identifies the
current maximum parallelism and frontier.

## Governed execution

The lower-level CLI groups mirror the protocol for operator recovery:

```text
capability request|inspect|revoke
work create|submit|discard
candidate converge|evidence
action inspect|respond
integration land|reconcile
publication publish
```

Each state-changing request may carry `--operation-id` for idempotency. Capabilities return bearer
tokens once. Inspection and handoff redact them.

Destructive cleanup binds the exact sorted ref list as compact JSON. For example, a discard of one
attempt requests `work.discard` with resource
`["refs/invariant/work/change-id/unit-id/attempt-id"]`; the resulting token is usable only with
that exact list.

Resolution and execution tokens are not interchangeable:

- `intent.resolve` answers one bound action and may be given to an eligible model actor.
- `worktree.create`, `worktree.write`, `verification.run`, `candidate.converge`,
  `integration.land`, `remote.publish`, `change.invalidate`, and `work.discard` govern operational
  consequences.

## MCP

```bash
invariant-mcp \
  --repository /absolute/path/to/repository \
  --principal harness:local
```

The stdio gateway exposes typed tools only. It has no generic command, repository, Git, environment,
network, remote, or credential parameter. Restarting it reloads the same ledgers and refs.

Denied, stale, and needs-input results are successful protocol exchanges. They do not authorize a
bypass.

## JSON envelope

Use `--format json` before the command:

```bash
invariant --format json change inspect change-id
```

Every result has:

```json
{
  "protocol": 2,
  "command": "change.inspect",
  "status": "ok",
  "outcome": "completed",
  "result": {},
  "diagnostics": []
}
```

Outcomes `completed`, `ready`, `needs_input`, `denied`, and `stale` exit zero. Mechanical blocks
exit one. Invalid input, corrupt state, transport failures, and internal failures exit two.
