## Invariant lifecycle

- Use the `invariant` CLI for repository mutations; do not reproduce its branch, receipt,
  verification, or landing mechanics.
- Keep evidence separate from accepted authority. Preserve unresolved contradictions as audits or
  discoveries instead of silently selecting an interpretation.
- `authority` controls semantic decisions. `execution` controls lifecycle pauses. Neither setting
  authorizes deployment, publication, or destructive external actions.

### Start and implement

Choose a short task ID and begin before the first mutation:

```bash
invariant --format json task begin <task-id> --goal <text> \
  [--boundary <no-record|recorded|unresolved|audit:id>] \
  [--path <path>]... [--interface <name>]... [--domain <id>]...
```

Implement and commit only in the returned `WORKTREE`; Invariant leaves the primary repository
checkout on the integration branch so other tasks can start concurrently. Run `invariant task
guidance <task-id>` whenever the task is resumed or context is compacted; add `--full` only when the
detailed reasoning handbook is needed.

### Finish

From the primary repository checkout, run:

```bash
invariant --format json task finish <task-id>
```

For routine candidates, `task finish` prepares the assessment, verifies the exact prospective tree,
compare-and-swaps the local integration ref, and cleans the task worktree in one command. If
semantic decisions or adapter review remain, it returns typed actions with `outcome: needs_input`.
Resolve each with `invariant task respond <task-id> <action-id> --input <file>`; never edit task
runtime. A failed finish keeps the integration ref unchanged and retains the worktree for recovery.
Expand a pending response schema with `task action`; list or retrieve exact-tree observations with
`task evidence`. Completed task status and evidence remain queryable from the archive.

Use `invariant task status <task-id>` for lifecycle state and `invariant task guidance <task-id>` for
the complete stage-specific protocol, locator forms, architecture context, and human escalation
rules. Use the published `evidence audit schema`, `task assessment schema`, and `task intent-brief
schema` commands instead of inspecting Invariant's implementation.

### Governance passes

When initialization requests a governance pass, run `invariant governance begin <task-id>`. The
first pass establishes durable governance; later passes reconcile it with the current committed
integration state. The returned guidance keeps audit, adoption, verification, and landing as
distinct internal phases. With agent authority, proceed without routine approval pauses; with human
authority, present concise behavior-level choices before adoption. Put unambiguous record
projections in the audit and use `governance project` plus `governance coverage`; edit the generated
adoption draft only where the audit-to-record mapping is genuinely ambiguous.
