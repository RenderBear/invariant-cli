## Invariant lifecycle

### Core operating rules

- If `invariant init` left configuration or instruction files uncommitted, commit that one-time
  bootstrap before beginning the first managed task.
- Use the `invariant` CLI for every repository mutation. Do not invoke Invariant's internal scripts
  or reproduce its branch, receipt, verification, or landing mechanics.
- The CLI owns the fixed lifecycle and its Git state. The agent owns implementation and semantic
  judgment.

### Start or resume a task

A task ID is the caller-chosen identifier for one managed repository change. Choose a short,
descriptive value such as `fix-job-recovery`; begin with a letter or number and use only letters,
numbers, `.`, `_`, and `-`. Reuse that exact ID throughout the task.

Before the first mutation:

1. Interpret the requested outcome.
2. Select any relevant semantic domains.
3. Include the durable-meaning boundary if it is already grounded; otherwise leave it unresolved
   until candidate review.
4. Begin the task:

```bash
invariant --format json task begin <task-id> --goal <text> \
  [--boundary <no-record|recorded|unresolved|audit:id>] \
  [--path <path>]... [--interface <name>]... [--domain <id>]...
```

To resume existing work, use:

```bash
invariant --format json task status <task-id>
invariant --format json task check <task-id> --goal-digest <digest>
```

If model context has been compacted, run `invariant task guidance <task-id>`. It compiles the
free-form brief, discoveries, coordination state, landing guidance, and human-translation guidance
applicable to the current stage.

### Implement the candidate

Implement and commit the requested change in the generated `WORKTREE` returned by `task begin`.
Leave the primary repository checkout on the integration branch and run lifecycle commands there. Keep
repository evidence separate from accepted architectural authority. Preserve unresolved
contradictions as evidence rather than silently choosing an interpretation.

`.invariant/` contains tracked governance and evidence plus ignored coordination runtime. Domains
name semantic responsibilities, not directories. Architecture Markdown is canonical; contracts
are executable cross-domain promises. Audits and discoveries are evidence, never authority. A
discovery records observation, causal basis, relevance, and disposition; it may resolve to
architecture, governance, implementation, documentation, tests, follow-up work, or no artifact.

### Prepare, verify, and finish

After committing the candidate, finish from the primary repository checkout:

```bash
invariant --format json task finish <task-id>
```

For a routine local candidate, `task finish` infers the assessment and continues directly through
verification and landing. When semantic decisions or adapter review remain, it returns typed
candidate-bound actions. Resolve each action through `task respond`; do not edit task runtime or
copy inferred locators into an assessment.

Use the explicit preparation command only to inspect or export the draft before finishing:

```bash
invariant --format json task assessment prepare <task-id>
```

`task finish` uses an existing prepared draft by default. Finishing recomputes reach, constructs and
verifies the exact prospective tree, runs affected verifiers, compare-and-swaps the local integration
ref, and cleans the task receipt, generated branch, and managed worktree. A failure leaves the
worktree recoverable and the integration checkout unchanged.

Use the published `evidence audit schema` and `task assessment schema` commands instead of
inspecting Invariant's implementation.

### Run a governance pass

Start a governance pass before creating its audit artifact. The first pass establishes durable
governance; a later pass reconciles existing records with the current committed integration state:

```bash
invariant governance begin <task-id>
```

Investigate without interrupting the human for code-level details, then save the completed
version-1 findings:

```bash
invariant governance audit-save <task-id> --input <findings-file>
```

Invariant saves the artifact as `audit-<UTC timestamp>.yml` and stamps the same event as
`created_at`, along with its ground and exact tree. The audit remains evidence rather than
authority.

#### Agent authority

Under `authority: agent`, continue directly from the saved audit through adoption. Establish the
smallest justified domains and architecture, attach executable verifiers to relied-on contracts,
preserve unresolved contradictions as discoveries, and land all repository changes through the
managed task lifecycle. Do not insert a routine approval stop between audit and adoption.

#### Human authority

Under `authority: human`, stop after saving and summarizing the audit. Let the human request deeper
investigation, adopt all ready findings, adopt selected findings, or defer adoption. `execution`
independently controls branch and landing pauses after the semantic decision has been made.

### Handle progressive discoveries

When repository work exposes a potential discovery, assemble its paths, searched scope, evidence,
and relevance without asking the human for code-level details.

- Under `authority: human`, the first capture or resolution attempt returns an approval proposal
  without mutating tracked state. Present the observation and the decision needed—not the internal
  fields—and rerun the same transition with `--apply` only after approval.
- Under `authority: agent`, proceed when the request and accepted repository authority are
  sufficient.

### Respect authority, execution, and publication boundaries

- `authority: agent | human` controls who defines repository-wide semantics and resolves conflicts.
- `execution: auto | assisted` controls lifecycle pauses. Both modes preserve the same stages and
  checks.
- Neither setting authorizes deployment, artifact publication, destructive cleanup, or other
  external effects.
- Remote Git publication is separate repository policy and defaults to `push_remote: off`.

When accepted configuration and the verified candidate both keep remote publication on, a
successful landing pushes the exact landed commit only to the integration branch's existing
upstream. Never choose or configure an upstream automatically, and never run `git push` outside
Invariant's landing flow. If the remote rejects the update, preserve and report the completed local
landing.

Repositories may enable the bundled `adapters.intent_brief` unit. It expands the request into a
Git-local prose brief and may ask only material questions. After the CLI collects exact-tree
evidence, the adapter returns one verdict over the whole brief before landing. Respond through the
action API; do not edit task runtime or transcribe check output. When disabled, the fixed Invariant
lifecycle remains unchanged.
