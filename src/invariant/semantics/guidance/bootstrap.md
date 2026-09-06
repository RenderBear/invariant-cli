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

Implement and commit only in the returned `WORKTREE`; Invariant leaves `LIFECYCLE-ROOT` on the
integration branch so other tasks can start concurrently. Run `invariant task guidance <task-id>`
whenever the task is resumed, context is compacted, or detailed semantic guidance is needed.

### Finish

From `LIFECYCLE-ROOT`, run:

```bash
invariant --format json task finish <task-id>
```

For routine candidates, `task finish` prepares the assessment, verifies the exact prospective tree,
compare-and-swaps the local integration ref, and cleans the task worktree in one command. If
semantic decisions or adapter evidence remain, it saves complete drafts and returns every missing
requirement together. Review and complete those files, then rerun the same command. A failed finish
keeps the integration ref unchanged and retains the task worktree for recovery.

Use `invariant task status <task-id>` for lifecycle state and `invariant task guidance <task-id>` for
the complete stage-specific protocol, locator forms, architecture context, and human escalation
rules. Use the published `evidence audit schema`, `task assessment schema`, and `task acceptance
schema` commands instead of inspecting Invariant's implementation.

### Governance passes

When initialization requests a governance pass, run `invariant governance begin <task-id>`. The
first pass establishes durable governance; later passes reconcile it with the current committed
integration state. The returned guidance keeps audit, adoption, verification, and landing as
distinct internal phases. With agent authority, proceed without routine approval pauses; with human
authority, present concise behavior-level choices before adoption.
