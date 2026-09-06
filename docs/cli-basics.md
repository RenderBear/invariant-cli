# Invariant CLI basics

Invariant is normally driven by a coding agent or harness. Humans can initialize a repository,
inspect its status, and change configuration without learning the full agent protocol.

## What is a task ID?

A task ID is a caller-chosen, repository-local name for one managed change. It connects the task's
goal, disposable receipt, generated worktree, verification, and final landing.

Use a short descriptive value such as `fix-job-recovery` or `PROJ-142`. It must begin with a letter
or number and may contain letters, numbers, `.`, `_`, and `-`. The same ID is passed to each command
for that task. It is not a Git commit or filename, and it does not need to match an external issue
unless that convention is useful to the repository.

For example, in this command `fix-job-recovery` is the task ID:

```bash
invariant task begin fix-job-recovery --goal "Restore active jobs after restart"
```

## Commands a human may use

Initialize the current repository:

```bash
invariant init
```

See repository health and active task IDs:

```bash
invariant status
```

Inspect one active task:

```bash
invariant status fix-job-recovery
```

Inspect the effective configuration:

```bash
invariant config show
```

With `execution: assisted`, Invariant may ask for an explicit local lifecycle continuation:

```bash
invariant task continue fix-job-recovery --apply
```

The coding agent should explain the proposed branch or landing action before asking a human to run
or approve that command.

## A typical agent-managed change

The following is an illustrative sequence. A coding agent or harness usually supplies the detailed
scope and runs these commands.

```bash
# Open the managed task and linked worktree.
invariant --format json task begin fix-job-recovery \
  --goal "Restore active jobs after restart" \
  --path src/jobs.py

# Commit in the returned WORKTREE, then finish from LIFECYCLE-ROOT.
invariant --format json task finish fix-job-recovery
```

For a routine local candidate, `task finish` infers the assessment and continues through exact-tree
verification and landing. If semantic decisions remain, it saves an editable draft in Git-local
runtime and returns all missing requirements together. Complete the draft and rerun the same
command. `task assessment prepare` remains available for explicit inspection. A failed finish
preserves the task receipt and managed worktree so the same task ID can be inspected and resumed.

When `adapters.task_acceptance` is enabled, `task begin` first asks the agent for a local acceptance
contract. The adapter preserves the original goal digest, expands the request, and records an
`inspection`, `targeted`, or `broad` verification level. After implementation, `task finish` also
writes a candidate-bound review beside that contract. The agent resolves its results
with proportional evidence before finishing; a local button-label change may use source or visual
inspection rather than a new persisted test.

## Governance passes

A governance pass is one resumable session with distinct audit, adoption, and verification phases.
The first pass establishes durable governance. Run it again with a fresh task ID after committed
repository changes to reconcile stale or incomplete governance:

```bash
invariant governance begin governance-baseline
invariant governance audit-save governance-baseline --input findings.yml
```

The saved file is named `audit-<UTC timestamp>.yml`; its YAML also carries the RFC 3339
`created_at` value and exact Git ground and tree.

With agent authority, the agent continues through ready findings without a routine approval stop.
With human authority, it summarizes the saved audit and offers deeper investigation, adoption of
all ready findings, adoption of selected findings, or deferral.

```bash
invariant governance adopt governance-baseline --all-ready
invariant governance adopt governance-baseline --finding recovery-ownership
invariant governance defer governance-baseline
```

## Agent and harness interfaces

The remaining command groups are primarily integration surfaces:

| Group | Purpose |
|---|---|
| `task` | Manage the fixed brief, branch, assessment, verification, and landing lifecycle. |
| `governance` | Coordinate a repeatable repository-wide audit and adoption pass. |
| `context` | Retrieve affected domains, architecture, contracts, reach, and digests. |
| `evidence` | Frame and save audits or capture progressive discoveries. |
| `coordinate` | Manage temporary plans and causal leases for concurrent work. |
| `candidate` | Expose exact-candidate verification and landing mechanics. |
| `state` | Validate tracked Invariant configuration, governance, and evidence. |

Use `--help` at any level for command syntax. Audit and assessment inputs are self-describing:

```bash
invariant evidence audit schema
invariant evidence audit example
invariant task assessment schema
invariant task assessment example
invariant task acceptance schema
invariant task acceptance example
```

For automation, `--format json` emits the compact protocol envelope. Add `--verbose` only when the
full human-readable rendering is also needed.
