# Invariant CLI basics

Invariant has one small human-facing command surface. It connects to a native Codex or Claude Code
installation and owns the repository lifecycle around that provider. Detailed protocol commands
remain available to agents and automation.

| Scope | Commands |
| --- | --- |
| Global | `connect`, `help`, and `--version` work anywhere on the machine. |
| Local | `init`, `ask`, `start`, `change`, `establish`, `source`, `status`, `settings`, and `set` operate only on the current Git repository. |

## First-time setup

Install and authenticate at least one provider CLI once on the machine. Invariant does not install
providers into repositories and does not store their credentials.

```bash
invariant connect
invariant connect codex       # or: invariant connect claude
invariant connect --default codex
```

`connect` without a provider is a read-only status check. With a provider, it runs that CLI's native
login only when needed. The working default is shown as `AGENT`; other connected providers are
`AVAILABLE`, while unconfigured alternatives are `OPTIONAL`, not failed setup. `--default
codex|claude` connects and switches the machine preference. Provider account eligibility, quota,
and billing remain with that CLI.

Initialize the repository and optionally override the machine default for this clone:

```bash
invariant init
invariant set harness claude
invariant set harness auto
```

Initialization attempts the selected coding agent's native connection. Without a clone-local
preference, it tries the machine default first and then the other supported provider. A failed attempt
is shown as a warning, skipped, and does not stop setup. The provider preference lives under
`.invariant/runtime/` and is never committed, so another machine's choice cannot break a fresh clone;
initialization never creates or modifies `AGENTS.md` or `CLAUDE.md`.

At the end of interactive initialization, Invariant asks one yes-or-no question about establishing
durable repository records. Choosing no finishes initialization and shows `invariant establish`.
`init` has no establishment flags. Non-interactive `--defaults` seeds the repository and reports the
separate establishment command.

Ordinary interactive setup asks for authority, execution, landing branch, publication, and
intent-review policy. To accept agent authority, automatic execution, the current branch,
local-only publication, and no intent-review add-on without those questions, use:

```bash
invariant init --defaults
```

Without a local preference, Invariant prefers the connected machine-default harness and then the
other available harness.
On a clean repository, `init` commits its deterministic setup locally; when prior uncommitted work
exists, it leaves the initialization unstaged for review.

Running `invariant init` again against a complete configuration warns before the questionnaire. The
default choice keeps the current file untouched; choosing replacement runs setup and replaces every
repository setting. Use `invariant set <key> <value>` when changing only one setting.

## Everyday commands

Ask a read-only question:

```bash
invariant ask "Where is retry behavior defined?"
```

Start a repository conversation:

```bash
invariant start
invariant start "Where is retry behavior defined?"
invariant set mode change
```

The default `ask` mode is read-only. `change` mode still uses a read-only conversational
coordinator, but it may classify a turn as an implementation request and route that request through
the ordinary managed-change lifecycle. It may also answer questions. The saved mode is local
ignored runtime state, not a tracked repository decision.

Each `start` is a foreground console. It does not stop sessions running in other terminals. Within
one console:

| Command | Effect |
| --- | --- |
| `:mode ask\|change` | Switch the active conversation's capability. |
| `:new [message]` | Create and enter another conversation. |
| `:sessions` | List conversations held by this console. |
| `:switch N` | Return to a listed conversation. |
| `:status` | Show deterministic repository status without invoking the agent. |
| `:settings` | Show repository settings. |
| `:set KEY VALUE` | Update one repository preference. |
| `:source add ...` | Add one scoped grounding source through the managed lifecycle. |
| `:exit` or Ctrl-C | End the console. |

Add a grounding source with one URL or path and one scope:

```bash
invariant source add --url https://example.com/api.json --scope contract:payments-api
invariant source add --path sources/backend.md --scope domain:backend
invariant source add --url https://example.com/standards --repo
```

`--path` is relative to `.invariant/` and must remain beneath `.invariant/sources/`. `--scope`
accepts an exact `domain:<id>` or `contract:<id>`. Other values are resolved as natural language;
quotes group multiword descriptions. Natural resolution is read-only and may select only an
already accepted domain or contract. `--repo` applies throughout the current repository. Source
content is presented to agents as untrusted evidence and cannot create semantic records or
authorize repository work.

Request a managed write:

```bash
invariant change "Restore active jobs after restart"
```

Invariant generates a change ID, opens an isolated worktree, invokes the selected provider there,
commits the proposed change, captures evidence, checks the exact tree, resolves conflicts within
the configured decision mode, and lands it locally. Use an explicit ID only when another system
needs one:

```bash
invariant change --id PROJ-142 "Restore active jobs after restart"
```

Before implementation, `change` decides whether the request is one coherent work item or contains
genuinely independent work. Small changes stay single. Disjoint ready work items run concurrently in
isolated worktrees. When one work item creates or changes a contract, its consumers wait and then
start from the converged contract snapshot; unrelated frontend and backend work may still proceed in
parallel.

Invariant validates the proposed execution plan before starting any worker. It gives the planner up
to two chances to repair concrete plan errors and falls back to a single work item when safe
parallelism is unclear. Generated tool caches do not count as worker output. If an independent
review rejects a candidate, `change` shows and retains its defects, sends them back to the author for
a bounded correction, reruns the checks, and asks a fresh reviewer before landing.

Establish or refresh durable repository records:

```bash
invariant establish
```

Inspect without model invocation:

```bash
invariant status
invariant settings
invariant ask --dry-run "Where is retry behavior defined?"
invariant change --dry-run "Restore active jobs after restart"
invariant establish --dry-run
```

Drop a preserved establishment and its proposal without starting another:

```bash
invariant establish --discard
```

`--using codex|claude` overrides the repository provider for one operation. `--id` supplies a stable
change or establishment identity for automation. If a contract decision is required or the run mode
asks for confirmation, the operation stops with its generated ID and a concrete continuation.

## Human vocabulary

The human surface uses a small vocabulary even though the underlying protocol is more detailed.

| Term | Meaning |
| --- | --- |
| Request | The outcome the user asks for. |
| Session | One foreground repository conversation with retained context. |
| Harness | The connected coding agent used for reasoning and implementation. |
| Change | One managed attempt to fulfill a request. |
| Plan | Ordered or parallel work items for a change. |
| Work item | One bounded part of a plan. |
| Reserved work | Scope currently assigned to one work item. |
| Proposed change | The exact repository state being checked before landing. |
| Record | Durable accepted meaning that future changes should preserve. |
| Domain | A named, stable responsibility in the system. |
| Contract | An accepted executable promise on which another domain relies. |
| Decision | An accepted architectural choice and its revision conditions. |
| Constraint | An accepted restriction on future implementation. |
| Source | A URL or repository-held document used as attributable grounding. |
| Evidence | A grounded observation supporting or challenging an interpretation. |
| Finding | A tracked observation that has not necessarily become an accepted record. |
| Conflict | A finding that identifies disagreement between a request, record, contract, domain, or observed code. |
| Delegation | Explicit permission for an agent to make a bounded class of decisions. |
| Check | A test, schema check, command, or other executable observation. |
| Land | Atomically apply the checked change to its local landing branch. |

Status uses `ready to resume`, `needs retry`, `needs confirmation`, `needs your decision`,
`needs attention`, and `complete`. These are persisted states, not process states: Invariant has no
background workers, and model-backed operations run only in the foreground command that invoked
them. Impact is rendered as `routine`, `covered`, `unclear`, `records updated`, or `contract
change`. Findings remain `open` until they have an attributable resolution.

Terms such as governance, disposition, reach, boundary, candidate, unit, and lease belong to the
automation protocol and do not appear in normal human output.

## What is a task ID?

The protocol calls the internal lifecycle unit a task. Human commands call it a change and generate
the ID automatically. A task ID connects the goal, disposable receipt, generated worktree,
verification, and final landing. It is not a Git commit or filename.

Low-level callers may choose a short value such as `fix-job-recovery` or `PROJ-142`. It must begin
with a letter or number and may contain letters, numbers, `.`, `_`, and `-`. The same ID is passed to
every low-level command for that task.

## A typical agent-managed change

The following is an illustrative sequence. A coding agent or harness usually supplies the detailed
scope and runs these commands. Humans normally use `invariant change` instead.

```bash
# Open the managed task and linked worktree.
invariant --format json task begin fix-job-recovery \
  --goal "Restore active jobs after restart" \
  --path src/jobs.py

# Commit in the returned worktree, then finish from the repository checkout.
invariant --format json task finish fix-job-recovery
```

For a routine local candidate, `task finish` infers the assessment and continues through exact-tree
verification and landing. If semantic decisions remain, it returns one or more typed `actions`
with `outcome: needs_input`. Submit each response through the action ID; do not edit runtime files:

```bash
invariant --format json task respond fix-job-recovery core:candidate-review \
  --input semantic-review.yml
```

The default lifecycle result contains stable action references and candidate evidence IDs. Fetch
the prompt, response schema, candidate context, or individual observations only when needed:

```bash
invariant --format json task action fix-job-recovery core:candidate-review
invariant --format json task evidence fix-job-recovery
invariant --format json task evidence fix-job-recovery state:<id>
```

`task assessment prepare` remains available for low-level inspection. A failed finish
preserves the task receipt and managed worktree so the same task ID can be inspected and resumed.
Successful completion archives the brief, review packet, evidence, final receipt, and a compact
`summary.yml` under `.invariant/runtime/history/`, keyed by the landed commit. `task status` and
`task evidence` continue to work after completion.

When `adapters.intent_brief` is enabled, the single `task begin` creates the normal isolated worktree
and returns a `task.created` action. The adapter writes one prose brief and asks only questions whose
answers would materially change implementation or acceptance. After implementation, `task finish`
collects mechanical evidence and returns a `candidate.evidenced` action. Its response is one verdict
over the whole brief—not a matrix of placeholders or manually transcribed check results.

These are hook actions, not adapter-owned stages. The core still owns receipt freshness, branch
isolation, candidate construction, exact-tree verification, assisted transitions, compare-and-swap
landing, and cleanup. A changed goal, brief, adapter implementation, or candidate tree invalidates
the corresponding response.

## Establishing repository records

Establishment is one resumable session with distinct investigation, record creation, and checking
phases. The first pass establishes durable records. Run it again after committed repository changes
to reconcile stale or incomplete records:

```bash
invariant establish
```

The bare command resumes the latest compatible unfinished establishment; an explicit ID is not
needed after a stopped run. A failed step reports its first concrete problem, confirms what was
saved and that no process is still running, then names the next task and its command. It also offers
`--discard` when dropping the saved proposal is preferable. With agent authority, retrying an older
invalid generated projection returns the attempt to investigation so the same command can correct
it instead of replaying a proposal that cannot pass. Equivalent older attempts collapse into one
`Repository records` item in human-facing status.

Selected findings that carry complete record projections are projected directly. When a selected
finding has none, the command asks the agent to author the missing domain, contract, constraint, or
semantic records from that finding's evidence, or to defer it with a reason, before verification.
Establishment reserves every domain that already exists on the integration branch, so a later pass
may re-record one; that is reconciliation, not a scope expansion.

With agent authority and automatic execution, the agent owns finding selection and the lifecycle
owns projection, checking, and landing. With human authority, the same command asks only which
findings to record and whether to accept the exact proposal, which it lists by record and file
before asking; it translates those answers into the protocol and continues the mechanics itself. A
selection whose projection is rejected reopens the finding choice on the next run. Declining the
proposal is an ordinary outcome, not an error: the exact proposal stays available for another
look or for `--discard`.

The completion panel names the records that landed. When the audit produced nothing to record,
the panel is titled `Audit recorded` and says so; the audit itself still lands as evidence.

The equivalent protocol sequence begins with:

```bash
invariant governance begin governance-baseline
invariant governance audit-save governance-baseline --input findings.yml
```

The saved file is named `audit-<UTC timestamp>.yml`; its YAML also carries the RFC 3339
`created_at` value and exact Git ground and tree.

When the agent may decide, it continues through ready findings without a routine approval stop.
When the user must decide, it summarizes the saved audit and offers deeper investigation, recording
all ready findings, recording selected findings, or leaving them open.

```bash
invariant governance adopt governance-baseline --all-ready
invariant governance adopt governance-baseline --finding recovery-ownership
invariant governance project governance-baseline
invariant governance coverage governance-baseline
invariant governance defer governance-baseline
```

An audit finding can carry complete `records` projections. The project command materializes those
unambiguous mappings and validates the generated registries. If semantic content is missing, it
writes a draft whose unresolved entries must be mapped to records, retained discoveries, or
explicit deferrals; coverage reports every selected finding.

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
invariant task intent-brief schema
invariant task intent-brief example
invariant context semantics --path src/example.py
```

`context semantics` also accepts repeated `--domain` and `--interface` coordinates plus `--at` for
historical retrieval. Scoped queries return applicable active records; an unscoped query returns the
full index, including superseded records. JSON results retain open `relations` and `facets` and carry
the canonical-prose digest.

For automation, `--format json` emits protocol 1 with typed task state, actions, artifacts, and an
`outcome` such as `ready`, `needs_input`, or `awaiting_approval`. Add `--verbose` only when the full
human-readable rendering is also needed. `task guidance` is concise by default; use
`task guidance <id> --full` when the detailed reasoning handbook is genuinely useful.
