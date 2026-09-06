# Invariant CLI — design of record

Invariant is a repository-native control plane for long-running agentic work, delivered as a
portable command-line application. It records accepted architectural meaning and binds explicit
review assertions to repository changes while owning deterministic mechanics, the fixed repository
lifecycle, a small semantic protocol, and optional integrations for agents and automation. It does
not host or execute the model loop.

The design separates three concerns:

1. **Semantics** decides what the requested change means.
2. **Mechanics** calculates and enforces deterministic repository facts.
3. **Lifecycle** advances work through briefing, isolation, verification, and landing.

The CLI owns mechanics and lifecycle. A coding agent or harness owns repository investigation and
implementation. Humans provide goals, resolve escalated ambiguity or conflict, and may approve
lifecycle transitions; they are not expected to inspect repository internals. Explicit repository
configuration may authorize one bounded external effect—publishing a verified landing to an
existing Git upstream—and the host owns every other external effect. None of these layers may
silently assume another layer's authority.

## 1. Goals

Invariant answers:

1. Which accepted responsibilities, architecture decisions, and contracts may apply?
2. Which facts can be derived exactly from repository state?
3. Does a candidate preserve the accepted meaning selected by its semantic reviewer?
4. Which executable checks apply to that exact candidate?
5. Can a requested local ref update happen without races, hidden conflicts, or unverifiable
   mechanical claims inside this clone?

Invariant should be usable from:

- an interactive shell;
- a coding agent such as Codex;
- an IDE or desktop application;
- CI;
- a repository hook;
- a purpose-built agent harness.

No integration is privileged. The same CLI contract serves all of them.

## 2. Non-goals

Invariant does not:

- provide its own language model or conversation loop;
- implement the user's requested repository change;
- infer semantic domains from directory names;
- decide whether a new promise deserves authority;
- replace repository tests, code review, or deployment policy;
- treat cached content as model memory;
- infer or configure a remote destination, deploy, publish artifacts, perform destructive cleanup,
  or authorize unbounded external side effects.

## 3. Layer ownership

### 3.1 Semantics

Semantic work is normally performed by the coding agent, with human authority requested only when
accepted governance is insufficient or contradictory. It owns:

- interpreting the user's requested outcome;
- selecting relevant semantic domains;
- distinguishing architecture, contracts, and implementation detail;
- deciding whether durable meaning is unchanged, changed, or uncertain;
- interpreting audit evidence;
- authoring accepted governance;
- reviewing architecture against a candidate;
- resolving incompatible meaning within granted authority.

Semantic work produces explicit inputs to the CLI. The agent may inspect code and prepare those
inputs; the human supplies goals and decisions, not repository plumbing. Semantic output never gains
authority merely because a model said something or a path matched a pattern.

Skills may assist semantic work, but skills are optional adapters. They do not implement repository
state transitions, branch policy, caches, retries, or the execution loop.

### 3.2 Mechanics

The `invariant` CLI owns deterministic operations:

- parsing and validating tracked Invariant state;
- checking identifiers, references, and Markdown anchors;
- deriving path and package scopes;
- projecting selected governance;
- calculating content digests;
- detecting changed material;
- proving the installed Git supports required exact-candidate and linked-worktree operations before
  lifecycle mutation;
- constructing exact Git candidates;
- selecting declared verifiers;
- running checks against an exact tree and capturing their command, environment, result, output
  digest, and log as evidence;
- validating audit and lease freshness;
- detecting conflicts and concurrent ref movement;
- atomically updating a local ref when explicitly requested;
- pushing the exact landed commit to an existing upstream only when tracked policy opts in.

The CLI does not call a model or select semantic domains. It may prepare `no-record` for a
mechanically local or bounded routine candidate; reach never manufactures authority for an open or
gated transition. Other semantic assertions come from the caller and are validated against
mechanical facts.

### 3.3 Lifecycle

The CLI owns the fixed repository lifecycle. It owns:

- capturing the integration target and causal ground;
- creating and refreshing a task receipt;
- creating or reusing an isolated generated worktree;
- recording lifecycle state needed for resumption;
- constructing the prospective integration tree;
- requiring semantic inputs at the points where mechanics cannot decide;
- running exact-tree verification;
- atomically landing onto the integration target;
- optionally publishing that exact landing under explicit tracked policy;
- releasing associated leases, removing active work, and archiving the completed argument trail.

The host may be a coding agent, purpose-built harness, IDE integration, or automation system. It
owns the conversation, performs implementation inside the CLI-provided work context, supplies
semantic decisions, presents progress and approval requests to the human, and owns every external
effect beyond the optional configured Git publication step.

The lifecycle is fixed even when execution is automatic. Automation removes routine pauses; it does
not remove lifecycle stages or checks.

## 4. Application boundary

The CLI is a standalone local lifecycle application, but it is not an agent harness. Its primary
role is to be executed as a child process by a coding agent or another application. Direct human use
is limited to configuration, inspection, resolution support, and optional lifecycle control—not
repository investigation or implementation.

The dependency direction is always:

```text
human goals, authority, and optional approvals
          |
          v
coding agent / IDE / harness / automation
          | repository analysis + implementation + semantic protocol
          v
     invariant task lifecycle
          | deterministic mechanics
          v
      Git repository + .invariant
```

The CLI must never require the caller to expose its conversation internals. The caller supplies
arguments or a structured input document and receives structured results.

An external application can integrate at three levels:

1. **Shell binding** — execute `invariant --format json ...` and interpret its exit status and JSON.
2. **Typed tool binding** — expose selected CLI commands through function calling or MCP while the
   tool implementation invokes the CLI.
3. **Harness binding** — use an agent SDK or app-server to own conversations, approvals, and
   resumption while invoking the CLI as the repository mechanics tool.

The first form is the compatibility baseline. The other forms must preserve the same command,
lifecycle, and result semantics rather than reimplementing Invariant rules.

### 4.1 Fixed task lifecycle

In a repository whose agent instructions activate Invariant, every repository mutation is a managed
task and follows the same shape:

```text
begin
  -> receipt + isolated work branch
  -> task.created hook actions
  -> implementation by the host
  -> exact prospective tree
  -> reach + exact-tree mechanical evidence
  -> candidate.evidenced hook actions
  -> final verification
  -> atomic local landing
  -> optional configured upstream push
  -> active-state cleanup + completed argument archive
```

`invariant task begin` captures the target, gathers the mechanically available context, records the
semantic envelope, and creates or reuses a generated branch in a dedicated linked worktree. It
leaves the integration checkout unchanged so several tasks can begin concurrently in one clone and
returns the task worktree plus typed lifecycle state and actions. Git-common runtime paths remain an
implementation detail.

The initial durable-meaning boundary defaults to `unresolved`. A harness may provide a grounded
disposition early, but the CLI does not require a human or agent to predict candidate reach before
the candidate exists. Final boundary review remains mandatory during `task finish`.

`invariant task finish` generates its internal assessment, constructs the prospective candidate,
and captures applicable mechanical evidence. Routine candidates continue directly. When semantic
input remains, it returns typed actions with a successful `needs_input` outcome; the host resolves
them through `task respond`, never by editing task runtime. The last response continues into final
validation and compare-and-swaps the local integration ref. If verification or landing fails, the
worktree remains recoverable. When remote
publication is enabled, it occurs only after local landing; a rejected push leaves that verified
local landing intact and reports it explicitly.

Semantic acknowledgements are attributable assertions, not proof of reviewer comprehension. The
CLI can bind them to an exact tree, expose omissions, and preserve who asserted what; it cannot
distinguish careful reasoning from a rubber stamp.

An unrelated mergeable integration advance may be adopted without restarting semantics. Expanded
semantic scope, changed governing material, incompatible meaning, or a real conflict returns the
task to the relevant earlier stage.

The existing staged direct-edit path remains an explicit recovery path for work already performed on
the integration branch. It does not replace the normal generated-branch lifecycle and still requires
exact-tree verification and atomic landing.

### 4.2 Human ergonomics

The host translates semantic protocol into behavior-level decisions. Humans are not asked to
construct paths, domains, reach sets, boundary dispositions, architecture or governance locators,
checks, or assessment files. Those are agent-authored and mechanically validated integration data.

When human authority is required, the host presents the observation, confidence, practical
consequence, compatible options, recommendation, and one concrete approval or clarification. After
a governance audit it groups findings into ready, decision-needed, verifier-needed, and
evidence-only categories; confirms that the audit is saved; and offers deeper investigation,
adoption of all ready findings, adoption of selected findings, or deferral. Raw validation failures
remain available for diagnostics but are not treated as the human interaction design.

Human-translation guidance is package-owned and composed into stage-specific `task guidance`
output. It is not copied into persistent `AGENTS.md` or `CLAUDE.md` managed blocks; those blocks
contain only the durable lifecycle rules and agent protocol reference needed to invoke that guidance.

## 5. State and authority

Tracked repository state remains:

```text
.invariant/config.yml
.invariant/SEMANTICS.yml
.invariant/DOMAINS.yml
.invariant/CONTRACTS.yml
.invariant/audits/<id>.yml
.invariant/discoveries/<id>.yml
AGENTS.md and/or CLAUDE.md managed workflow block
```

Initialization creates the configuration and selected agent instruction integration. Domain and
contract registries are created only when accepted records exist; bootstrap does not manufacture
empty semantic authority.

Optional ignored coordination state remains:

```text
.invariant/runtime/plans/<id>.yml
.invariant/runtime/leases/<unit>.yml
```

Disposable local receipts remain outside repository state:

```text
<git-common-dir>/invariant/briefs/<task-id>.yml
<git-common-dir>/invariant/tasks/<task-id>/...
```

After a successful landing, task-local evidence and semantic inputs move to:

```text
<git-common-dir>/invariant/history/tasks/<task-id>/<landed-commit>/...
```

The standing of each object is:

| Object | Standing | Lifetime |
|---|---|---|
| Semantic record and canonical prose | accepted interpretation | repository history |
| Domain and contract projections | accepted authority | repository history |
| Audit, discovery | evidence only | repository history |
| Intent brief and candidate reviews | task-local semantic argument | archived after landing |
| Plan, lease | coordination only | active work |
| Active receipt | cache integrity only | active task |
| Git tree and commit | causal implementation fact | repository history |
| Verification result | reproducible observation for one exact tree | archived after landing |

Only accepted governance binds future work. Evidence can motivate governance but cannot become
authority without explicit adoption.

## 6. Configuration

Tracked repository configuration remains small:

```yaml
version: 1
coding_agents: [codex, claude]
authority: agent
execution: auto
integration_branch: auto
push_remote: off
adapters:
  intent_brief: off
```

`coding_agents` records the non-empty set of supported coding agents configured during repository
initialization. It controls instruction-file setup, not semantic authority or model execution.

`authority` names who may define repository-wide semantics, resolve conflicts, and approve durable
requirements:

- `human` previews discovery capture and resolution without mutation, then sends the semantic
  proposal to a human for approval;
- `agent` permits an agent to resolve meaning when the current request and accepted authority are
  sufficient.

The agent supplies causal evidence, searched paths, domains, and record structure in both modes.
The human supplies goals or authority only; after approval, the harness reapplies a human-authority
transition with `--apply`. Agent authority requires both accepted and proposed configuration to
remain `agent`: enabling takes effect after integration, while returning to `human` is immediate.

`integration_branch` identifies the default local convergence target. `auto` resolves the primary
lifecycle checkout's current branch when a new task begins; a named value fixes one existing local
branch as the convergence target. An omitted value is read as `auto` for compatibility.

`push_remote` is an independent remote-publication policy:

- `off` leaves every successful landing local;
- `on` pushes the exact landed commit to the configured integration branch's existing upstream.

Remote publication requires both the accepted configuration and the verified candidate to say
`on`. Enabling therefore takes effect only after the enabling configuration reaches the integration
branch, while disabling takes effect on the disabling candidate itself. Invariant never chooses or
configures a remote. A missing or unusable upstream blocks before local landing; a remote rejection
after local landing reports a blocked publication while retaining the local integration commit.

`execution` controls how the CLI advances its fixed lifecycle:

- `auto` advances every mechanically valid, authorized local transition without a routine pause;
- `assisted` presents state-changing transitions before applying them and waits for explicit
  continuation.

A full audit is read-only investigation, so `execution` does not gate it. The completed audit is
persisted under `.invariant/audits/` with its exact ground and tree before adoption. Adoption keeps
the two controls separate: `authority` determines who approves the findings, while `execution`
determines whether the resulting task branch, verification, and landing advance automatically.
With agent authority, audit through adoption is one autonomous governance pass. With human authority,
the saved audit is summarized before the human chooses deeper investigation, adoption of all ready
findings, adoption of selected findings, or deferral.

A governance pass is exposed as one resumable session while preserving distinct audit, adoption,
and verification phases. The first pass establishes durable governance; later passes reconcile it
with the current committed integration state. The managed worktree is opened before audit
persistence, eliminating an incidental audit-only commit between `audit save` and task creation.
Under agent authority, saving the audit automatically selects its ready findings and advances the
session to adoption.

Project-aware verifier runners may be registered under `verification.runners`. Each runner declares
a command template, repository-relative working directory, `exact-tree` or `never` cache policy,
and optional timeout. `runner:<name>#<target>` invokes it. Python `test:` locators locate the nearest
candidate `pyproject.toml` and use its tracked `uv.lock` when present. Automatic reuse is enabled
only for that locked environment; named runners must opt into exact-tree reuse explicitly.

Absence means both supported coding agents, `authority: agent`, `execution: auto`,
`integration_branch: auto`, `push_remote: off`, and no enabled adapters. Automatic
execution is the ergonomic default; it does not remove briefing, branch isolation, exact-tree
verification, or atomic landing. Neither execution mode weakens validation or grants external
authority.

`invariant init` is the repository bootstrap. Interactive invocation explains each setting and uses
arrow-key radio selection; only a named integration branch requires free-form typing. `--defaults`
selects both coding agents and every safe default without prompting. It creates
`.invariant/config.yml`, installs or updates a marked workflow block in the selected root agent
instruction files, and prints a natural-language request for the coding agent to run a governance
pass. Before writing those files it proves that Git provides the linked-worktree and
`merge-tree --write-tree` capabilities used by the lifecycle. It never runs a model itself. Existing
unrelated agent instructions are preserved, and an ambiguous unmanaged Invariant section blocks
initialization before project state is created.

`invariant config show` displays configured and resolved values without creating state.
`invariant config init` remains the lower-level configuration-only initializer.
`invariant config set <key> <value>` updates one validated setting atomically. The settable keys are
`coding_agents`, `authority`, `execution`, `integration_branch`, `push_remote`,
and `adapters.intent_brief`. Version `1` is the configuration schema marker, not an operational
setting.

Optional additions to the fixed core are configured under `adapters`. The bundled
`intent_brief` adapter demonstrates the hook API: `task.created` expands the original goal into one
prose brief and may interview the user; `candidate.evidenced` returns one whole-candidate verdict
after evidence collection. It cannot create stages, branches, checks, or ref updates. Both hook
responses use `task respond`. The model-led default leaves the adapter disabled and relies on the
coding agent's normal understanding plus normal candidate review.

## 7. Semantic model

### 7.1 Semantic records: an open envelope around prose

Invariant preserves an auditable interpretation, not an interpretation-free fact. The canonical
Markdown should store the argument: proposition, rationale, evidence considered, assumptions,
alternatives, consequences, and conditions for revision. The CLI deliberately does not parse those
sentences into a closed claim taxonomy.

`.invariant/SEMANTICS.yml` is a thin mechanical index:

```yaml
version: 1
records:
  - id: processor-source-ownership
    document: architecture:docs/architecture.md#processor-source-ownership
    authority: user:task:import-processor#turn-3
    status: active
    applies_to: [repo:services/document-processor, interface:processor-source]
    revisit_on: [repo:.gitmodules, repo:services/document-processor/.git]
    verifies: [command:checks/ordinary-processor-source.sh]
    supersedes: [processor-external-ownership]
    relations:
      challenges: [semantic:processor-external-ownership]
    facets:
      confidence: accepted
```

Only the fields needed for durable mechanics are fixed:

- `id` provides a stable identity;
- `document` points to the exact canonical prose section;
- `authority` explains why the interpretation may govern;
- `status` and `supersedes` preserve revision rather than overwriting history;
- `applies_to` retrieves the record from path, interface, or domain context;
- `revisit_on` reopens review when a dependency or contradiction trigger changes;
- `verifies` projects portions of the meaning into executable witnesses;
- `relations` and `facets` are open vocabularies for challenge, support, confidence, local
  terminology, or future repository-specific concepts.

The index therefore knows where meaning applies and when to revisit it, but not what the prose
means. A verifier failure challenges the interpretation; it cannot decide whether code, verifier,
or interpretation should change. Likewise, strong evidence has no authority by itself, while a
provisional decision may still be authoritative within its stated scope.

`revisit_on: semantic:<id>` forms an explicit dependency edge. Retrieval follows those edges so a
dependent interpretation is present when its premise is in context. Invalidation propagates only
when the premise's envelope or canonical prose changes—not whenever ordinary code covered by that
premise changes. Open `relations` never acquire this behavior implicitly.

When a landing records `semantic:<id>`, its commit also carries `Invariant-Semantic:
<id>@<sha256>`. The digest covers the normalized envelope and exact canonical Markdown section in
the candidate tree. Landing-history validation rejects missing, malformed, or stale bindings.

The older domain and contract registries remain supported as useful projections. They are not the
universal ontology.

### 7.2 Domains

A domain is a stable semantic responsibility and retrieval index. It is not a directory, package,
service, or ownership lock merely because those structures happen to align.

```yaml
version: 1
domains:
  - id: ocr.orchestrator
    responsibility: Selects OCR engines and distributes work.
    authority: user:task:ocr-architecture#turn-4
    parent: ocr
    architecture: [architecture:docs/architecture.md#ocr-orchestration]
    contracts: [ocr.engine-protocol.v1]
```

The CLI validates identifiers, parent references, cycles, contract references, and architecture
anchors. The semantic caller selects which domains apply to a task.

### 7.3 Architecture

Anchored Markdown sections hold rationale, responsibility boundaries, critical choices,
consequences, and revision conditions. The Markdown remains canonical; registry pointers establish
relevance, not truth.

```markdown
## OCR engine isolation

Provider-specific behavior remains inside its engine domain because orchestration must stay
provider-neutral. Revisit this if engines no longer share lifecycle or replacement semantics.
```

Architecture compliance requires semantic review against a concrete candidate. The CLI can locate
affected sections and validate a review acknowledgement, but it cannot perform the review.

### 7.4 Contracts

A contract is an accepted executable promise relied on across domains.

```yaml
version: 1
contracts:
  - id: ocr.engine-protocol.v1
    assertion: Every engine accepts OcrRequest and returns OcrResult.
    authority: user:task:ocr-architecture#turn-4
    between: [ocr.orchestrator, ocr.engine.external]
    surfaces: [interface:OcrEngine, repo:schemas/ocr-engine.json]
    architecture: [architecture:docs/architecture.md#ocr-engine-protocol]
    verifies: [command:scripts/verify-ocr-engine-protocol]
```

Contracts require identifiable reliance, referenced architecture, and executable verification. The
semantic assertion is reviewed by an agent or human; executable verifiers test stable observable
consequences of that assertion against the exact candidate tree. A verifier may be a conformance
suite, schema compatibility check, boundary integration test, state-machine property, or another
repository-owned observation. Passing is evidence for the contract, not a mechanical proof of every
possible interpretation. If a promise has no stable observable consequence, record it as
architecture or a constraint rather than pretending it is executable. The CLI selects and runs
declared verifiers; it does not invent contracts or tests.

### 7.5 Durable meaning

The semantic reviewer asks:

> Could a future change be locally reasonable but systemically wrong unless it knew and preserved
> a decision introduced or changed here?

A positive answer includes stable responsibility, relied-on interfaces or formats, authoritative
state ownership, persistence, consistency, transaction, failure, recovery, migration, rollout,
compatibility, or an architectural restriction. Change size and directory shape do not answer the
question.

The result supplied to verification is one of:

- `no-record` — accepted meaning and durable operational properties remain unchanged;
- `audit:<id>` — a fresh scoped audit concludes that no adoption is currently required;
- `recorded` — the change is owned by supplied accepted governance references.

These are semantic assertions with mechanical validation. A reach classification never manufactures
the assertion.

### 7.6 Intent-brief adapter

When `adapters.intent_brief` is enabled, `task begin` returns a `task.created` action whose response
is a task-local prose brief:

```yaml
version: 1
adapter: intent_brief
source_goal_digest: <goal-digest-from-task-begin>
brief: >-
  Restore each non-terminal job once when the browser is reopened. Keep chat events scoped to the
  current browser session and preserve existing recovery behavior for terminal jobs.
questions:
  - id: retention-window
    prompt: Must recovery survive expiry of the existing retention window?
    answer: No; preserve the existing window.
```

Questions are optional and may remain only when different answers would materially change the
candidate or its acceptance. The brief is an expansion of the original goal, not a replacement for
it and not repository governance. There are no outcome/acceptance/constraint mirrors or inert
verification labels.

At `candidate.evidenced`, the adapter receives the exact candidate tree, brief digest, goal digest,
and evidence already captured by core. It returns one `accepted`, `rejected`, or `uncertain` verdict,
one substantive summary, and genuine exceptions. It does not manually restate one result per
sentence or transcribe evidence the CLI already owns. A changed candidate, goal, brief, or adapter
implementation invalidates the review.

## 8. CLI contract

The executable is named `invariant`. Lifecycle and mechanical commands are composable and
non-interactive. Repository bootstrap is the deliberate exception: `invariant init` is interactive,
while `invariant init --defaults` is deterministic and non-interactive.

A task ID is a caller-chosen, repository-local identifier for one managed change. It begins with an
alphanumeric character, may contain alphanumerics, `.`, `_`, and `-`, and connects the task's goal,
receipt, generated branch, verification, and landing. For example, `fix-job-recovery` is the task ID
in `invariant task begin fix-job-recovery --goal "Restore active jobs after restart"`.

Initial command groups are:

```text
invariant init [--defaults]
invariant status [<task-id>]
invariant governance begin <task-id>
invariant governance audit-save <task-id> --input <findings-file>
invariant governance adopt <task-id> <--all-ready|--finding <id>...>
invariant governance defer <task-id>
invariant governance status <task-id>
invariant config show
invariant config init
invariant config set <key> <value>
invariant task begin <task-id> --goal <text> [semantic scope...]
                     [--intent-brief|--no-intent-brief]
                     [--intent-brief-file <file>]
invariant task status <task-id>
invariant task check <task-id> [semantic scope...]
invariant task finish <task-id> [--check <locator>]...
invariant task respond <task-id> <action-id> --input <file>
invariant task continue <task-id> [--apply]
invariant task invalidate <task-id>
invariant task guidance <task-id> [--full]
invariant task assessment <schema|example>
invariant task assessment prepare <task-id> [--output <file>]
invariant task intent-brief <schema|example>
invariant state validate
invariant context map
invariant context rows <domain>...
invariant context semantics [--path <path>]... [--domain <domain>]...
                            [--interface <interface>]... [--at <commit>]
invariant context digest [--at <commit>] <domain>...
invariant context reach [--base <ref>] [--path <path>]...
                        [--interface <name>]... [--domain <id>]...
invariant evidence audit <scope|full|schema|example> ...
invariant evidence audit save <audit-id> --mode <scope|full> --input <findings-file> ...
invariant evidence fresh <audit-or-discovery> [--at <ref>]
invariant evidence discovery <capture|resolve> ... [--apply]
invariant coordinate plan validate <plan>
invariant coordinate status [<plan>]
invariant coordinate lease <acquire|renew|release|list|fresh|reap> ...
invariant candidate verify <candidate> --assessment <file> [--check <locator>]...
invariant candidate land <candidate> --target <branch> --assessment <file>
```

The `task` group is the public lifecycle interface. The remaining groups expose inspectable
mechanical capabilities for diagnostics, CI, and testing; they do not provide an alternate path
around lifecycle invariants. The installed package owns the implementation and never invokes
package-relative skill scripts.

### 8.1 Structured input

Commands with semantic inputs accept a versioned assessment document:

```yaml
version: 1
goal_digest: <hash>
paths: [src/ocr/engine.py]
interfaces: [OcrEngine]
domains: [ocr.engine.external]
boundary:
  disposition: no-record
governance: []
architecture_reviews:
  - architecture:docs/architecture.md#ocr-engine-isolation
checks:
  - test:tests/test_ocr_engine.py
```

The assessment records the caller's semantic decisions. It is not accepted governance and need not
be committed. The CLI validates references, completeness, and consistency with the candidate.
`task finish` owns assessment preparation. If no semantic judgment remains, it proceeds in the same
command. Otherwise it returns action objects whose contexts contain the exact candidate tree,
affected semantics, inferred governance, and captured evidence. `task assessment prepare` exposes
the lower-level assessment for diagnostics and migration; normal hosts do not edit it.

Adapter inputs do not extend the core assessment schema. When the intent-brief adapter is enabled,
its final action accepts a separate whole-candidate review:

```yaml
version: 1
adapter: intent_brief
source_goal_digest: <goal-digest>
brief_digest: <brief-digest>
candidate_tree: <exact-tree-id>
verdict: accepted
summary: The exact candidate satisfies the whole intent brief and the collected evidence supports it.
exceptions: []
```

`invariant task intent-brief schema` exposes both adapter response shapes.

### 8.2 Structured output

Every command supports `--format text|json`. Text is for direct use; JSON is the application
integration contract. JSON is compact by default and never duplicates its human rendering;
`--verbose` adds that rendering explicitly for diagnostics.

JSON uses one envelope:

```json
{
  "protocol": 2,
  "command": "task.finish",
  "status": "ok",
  "outcome": "needs_input",
  "result": {
    "task": {
      "id": "example",
      "stage": "awaiting-review",
      "goal_digest": "<goal-digest>",
      "scope": {"paths": ["src/example.py"], "interfaces": [], "domains": []},
      "boundary": "no-record",
      "integration": {"target": "main", "base": "<base-commit>"},
      "work": {"branch": "invariant/work/example-<nonce>", "worktree": "<path>"},
      "adapters": [],
      "actions": [
        {
          "id": "core:candidate-review",
          "adapter": "core",
          "phase": "candidate.evidenced",
          "kind": "review_semantics",
          "blocking": true,
          "prompt": "Review the exact candidate against the affected canonical prose.",
          "input_schema": {},
          "context": {"candidate_tree": "<tree>"}
        }
      ],
      "artifacts": [],
      "completion": {"commit": ""}
    },
    "candidate": {"tree": "<tree>", "evidence": []}
  },
  "diagnostics": []
}
```

`outcome` distinguishes completed work, work ready for implementation, input suspension, and
assisted approval from actual failures. Stable diagnostic codes carry changed governance, stale
evidence, verification failure, conflict, or concurrent ref movement. Applications must use fields,
action IDs, and schemas—not parse human prose or inspect Git-common runtime paths.

Process exits remain deliberately small:

- `0` — the requested operation completed successfully;
- `1` — the operation completed with a valid blocking or negative result;
- `2` — invocation, state, or internal failure prevented a valid result.

Detailed distinctions belong in structured diagnostics rather than a growing exit-code taxonomy.

### 8.3 Lifecycle hook protocol

The hook surface contains only two blocking semantic suspension points. Mechanical steps are not
hooks: keeping them in core prevents an adapter from replacing branch isolation, evidence
collection, verification, or compare-and-swap landing.

| Phase | Ordering guarantee | Context | Allowed result |
|---|---|---|---|
| `task.created` | Receipt, target, base, branch name, and work location have been selected; implementation has not begun | task, original goal, goal digest | private state, artifacts, or blocking response actions |
| `candidate.evidenced` | One exact candidate tree has been constructed and its applicable mechanical observations captured; integration has not moved | task, goal digest, candidate tree, evidence receipts | private state, artifacts, or blocking response actions |

Each action contains a stable ID, owner, phase, kind, human prompt, JSON Schema, blocking flag, and
candidate-specific context. The CLI stores it in the active receipt and returns it in typed output.
`task respond` resolves exactly one ID. Adapter response files are transported through the CLI and
stored privately; they are never accepted governance merely because an adapter produced them.

Hook execution follows these rules:

1. Replaying a phase with unchanged context must return an equivalent pending request or recognize
   the already accepted artifact.
2. A response is checked against every available causal binding: goal digest at intake; goal,
   brief, and candidate digests at final review.
3. The task cannot implement while a blocking `task.created` action remains. Resolving the last one
   advances to implementation without a second begin.
4. The integration ref cannot move while a blocking `candidate.evidenced` action remains. Resolving
   the last one continues to landing automatically, except for an independent assisted-execution
   pause.
5. Changing a candidate while review is pending causes `task finish` to construct new evidence and
   invalidate the old candidate response. Rejection or uncertainty retains the worktree for repair.
6. An adapter owns only its private state and action semantics. It cannot choose lifecycle stages,
   invoke Git transitions, mark mechanical evidence passed, or authorize repository-wide meaning.
7. Core semantic review uses the same action transport, so hosts need one response API rather than
   a special assessment-file editing path.

There is intentionally no blocking post-update hook: after compare-and-swap succeeds, an optional
integration must not retroactively make the local landing ambiguous. Notifications or publication
beyond the separately configured upstream push belong to the host.

### 8.4 Output discipline

- Standard output contains only the selected result format.
- Successful verifier output is retained in ignored Git-local logs and summarized rather than
  copied into normal responses. Failure responses include the relevant output and log path.
- Standard error contains invocation or runtime diagnostics that prevented a valid result.
- Read-only commands never mutate Git, `.invariant`, runtime state, or receipts.
- State-changing commands identify every intended mutation before applying it and support a dry-run
  where the result can be computed without mutation.
- Repeating an idempotent command with unchanged inputs yields an equivalent result.

## 9. Reach

Reach combines mechanical intersections with semantic domains supplied by the caller.

Mechanical inputs include:

- changed repository paths;
- changed Markdown sections when hunks resolve precisely;
- declared contract surfaces;
- caller-supplied interfaces;
- caller-supplied semantic domains and their ancestors.

Reach results remain:

- `local` — no accepted binding record intersects;
- `bounded` — accepted architecture or contracts apply but are not changed;
- `open` — defining material, executable verification, or additive governance changes;
- `gated` — accepted governance is removed or rewritten.

Reach is evidence for semantic review and lifecycle choice. It does not dictate branch creation,
infer `no-record`, or authorize landing.

## 10. Candidate verification and landing

A candidate is identified by exact Git object identity. Initial candidate forms are:

- `commit:<sha>`;
- `branch:<ref>` resolved and captured at invocation;
- `staged` from an explicitly identified worktree and index;
- `merge:<base>:<tip>` constructed without moving either ref.

Verification:

1. constructs and captures the candidate commit and tree;
2. computes actual changed paths and section reach;
3. validates tracked Invariant state;
4. selects and runs affected semantic/contract verifiers and supplied repository checks;
5. records command identity, working directory, executable/environment fingerprints, timestamps,
   duration, status, exit code, output digest, and retained log;
6. presents those observations with the exact candidate to semantic review;
7. validates the resulting authority, architecture acknowledgements, governance references, and
   boundary disposition;
8. reruns volatile checks or reuses only exact-tree evidence whose declared cache policy permits it.

Standalone verification never updates a ref. Within `task finish`, verification is the mandatory
precondition to the same atomic landing operation.

Landing repeats or consumes verification only when the evidence exactly matches the candidate tree,
CLI mechanics version, verifier identities, and relevant governance versions. It then:

1. confirms the target still equals the captured head;
2. resolves an already-configured upstream before mutation when remote publication is enabled;
3. confirms the target worktree can be synchronized safely;
4. applies the requested local ref update atomically;
5. releases explicitly associated leases only after success;
6. pushes the exact landed commit to that upstream when enabled.

Any conflict, failed check, changed candidate, missing review, stale assessment, or concurrent target
advance leaves the target unchanged.

The host may use ordinary editing and Git inspection commands inside the generated work context, but
the managed task reaches the integration target only through atomic landing. Routine changes use the
same lifecycle with little or no semantic ceremony.

## 11. Audits and discoveries

An audit is tracked evidence over a declared commit and exact tree. The CLI can capture mechanical
scope, validate evidence references, and check causal freshness. A semantic reviewer authors its
findings and dispositions. `evidence audit save` accepts only a version marker and findings,
combines the audit label with a compact UTC timestamp, records the same event as RFC 3339
`created_at`, stamps the mode, ground, and tree, validates the complete record, and writes it under
`.invariant/audits/` before any adoption decision. Governance passes use the neutral label `audit`,
producing `audit-<UTC timestamp>.yml`. Time is descriptive only; freshness remains Git-causal.

A discovery is a tracked non-authoritative change in repository understanding:

```text
discovery = observation + causal basis + relevance + disposition
```

The observation and rationale remain prose. The basis binds evidence or an explicit searched scope
to a commit and exact tree. Relevance can name domains, paths, tasks, or related records. Disposition
is `open` or `resolved`; a resolution may point to architecture, a domain, a contract, code,
documentation, tests, another discovery, follow-up work, or no artifact at all.

This makes missing artifacts, contradictory behavior, implicit dependencies, meaningful absence,
and incomplete documentation normal discoveries. It does not assume that every discovery should
end in a contract. The older `pending | promoted | dismissed | superseded | stale` records remain
readable during migration.

Evidence changes can make an audit or discovery mechanically suspect. Whether changed evidence
contradicts a finding remains semantic judgment.

Discovery is agent-mediated. The coding agent supplies the observation, evidence, searched scope,
paths, domains, and related records. Under human authority, capture and resolution first return an
`authority_required` proposal and leave tracked state unchanged. The host presents only the
observation and required semantic decision to the human, then repeats the transition with `--apply`
after approval. Under agent authority, the transition proceeds within the granted scope. Detailed
evidence fields remain part of the harness protocol, not the human interface.

### 11.1 Repository archaeology and semantic reasoning

Managed guidance includes prose-rich repository archaeology and semantic reasoning. The purpose is
to reconstruct relevant architecture in repositories where code, tests, schemas, configuration,
documentation, history, and operational behavior may be incomplete or contradictory. Investigation
starts from the requested behavior, traces it through ownership, state, interfaces, time, failure,
and consumers, and expands only while new evidence could change implementation, durable-boundary
judgment, or verification.

Stable semantic IDs, paths, interfaces, domains, and revisit triggers are retrieval and invalidation
coordinates. They do not bound the form of semantic reasoning or replace its prose. The semantic
pass keeps requested meaning, accepted repository meaning, and observed behavior distinct; records
disagreement rather than silently choosing a source; and treats bounded absence as evidence only
when the searched scope and exact tree are explicit.

`task guidance` compiles the selected context rather than merely printing locators. It includes:

- the task's prose intent brief, when enabled;
- selected durable rows and their anchored architecture sections at the captured integration head;
- the observation, basis, evidence, searched scope, and relevance of open discoveries intersecting
- the prose guidance applicable to the current stage.

Default guidance is the concise stage core. `--full` adds repository archaeology, the detailed
semantic reasoning handbook, discovery/coordination material, and protocol reference.

Architecture is read from the captured accepted ground so candidate edits cannot silently rewrite
the premise used to interpret their own change. Discoveries remain non-authoritative and may evolve
progressively; including their prose in context does not promote them to governance.

When the resolution does adopt durable governance, it edits the smallest canonical architecture,
domain, or contract record and then runs `invariant state validate`. The CLI validates adoption; it
does not manufacture accepted meaning.

## 12. Coordination

Coordination is optional and activated only by the host when work is genuinely parallel,
independently owned, or handoff-sensitive.

Plans describe units, dependencies, path/interface/governance claims, provides/relies relationships,
and checks. Leases record temporary ownership against an integration ground and causal branch tip.

The CLI mechanically validates:

- target and ground existence;
- acyclic dependency order;
- provider-before-consumer edges;
- unordered claim overlap;
- selected governance digests;
- lease freshness and liveness facts.

The CLI does not decide to create workers or maintain conversations. Those are harness concerns.

Core context and candidate verification must not depend on coordination runtime. Coordination may
depend on context mechanics, never the reverse.

## 13. Receipts and caching

A receipt is disposable lifecycle state and an integrity cache for repeated semantic work. Every
managed task creates one during `task begin`. It is never consumed as landing evidence.

A receipt may bind:

- repository identity;
- brief-dependency mechanics digest;
- integration target and captured head;
- exact goal digest as a textual drift detector;
- selected paths, interfaces, and domains;
- selected governance and defining-material digests;
- the current boundary disposition.

The receipt keeps these concerns separate. `governance_snapshot` contains `selected_digest` and
`integration_digest`, which are freshness baselines only. `change_classification` contains the
task's `boundary` and optional `posture`; it describes the change without granting authority.

The CLI reports changed dependencies. The semantic caller decides whether changed goal text remains
compatible with the cached envelope. Successful confirmation may refresh the exact goal digest only
after every mechanical freshness check succeeds.

The mechanics digest covers only configuration, Git identity, governance selection, material-change,
serialization, and receipt-compatibility code. Landing, coordination, presentation, and prose
guidance do not evict the brief cache: they are recomputed or reloaded independently. Receipts do not
hash skill packages. Skill loading and context compaction belong to the host. Verification evidence
may be reused only for the exact tree and base, verification mechanics version, runner configuration,
working directory, executable environment, and verifier identity that produced it; changing the
candidate always invalidates that evidence. Active receipts and logs live under Git-local Invariant
runtime. On successful landing, the task receipt, evidence, brief, and reviews are archived under
`invariant/history/tasks/<task>/<landed-commit>/`; active task state disappears. Reach, semantic
reviews, candidate state, prospective-tree construction,
and compare-and-swap target checks are always recomputed even when an expensive verifier result is
reused. Volatile runners use `cache: never`.

## 14. Lifecycle profiles

Invariant has one mandatory managed-task lifecycle and two execution profiles.

### 14.1 Automatic execution

With automatic execution, the CLI:

1. opens or refreshes the task receipt;
2. creates or reuses an isolated linked worktree without moving the integration checkout;
3. exposes any `task.created` action and then returns control for implementation;
4. resumes at `task finish`, captures candidate-bound evidence, and exposes any
   `candidate.evidenced` actions;
5. advances through final verification and local landing after the last action is resolved;
6. stops only for missing semantic authority, failed checks, conflict, concurrent movement, or
   unauthorized external effects.

### 14.2 Assisted execution

With assisted execution, the CLI performs the same stages but presents proposed state-changing
transitions and waits for `task continue --apply` before branch creation, governance adoption, or
local ref update.

Both profiles preserve the same receipts, branches, candidate construction, checks, and landing
guarantees. The distinction is only where the CLI pauses.

### 14.3 Intent-brief adapter

With the bundled adapter enabled, the single `task begin` creates or reserves normal isolated work
and returns a `task.created` action. The task enters `briefing` only while material intent input is
pending; `task respond` advances it without replaying begin. `task finish` then captures evidence
for the exact candidate and returns a `candidate.evidenced` whole-intent review. A changed tree,
brief, goal, or adapter implementation invalidates the review.

When disabled, those adapter actions disappear. Core semantic review still uses the same action
transport when durable meaning is affected. Receipts, generated branches, candidate-bound evidence,
exact-tree verification, and atomic landing remain mandatory core behavior.

## 15. Skills

Skills remain useful only where model judgment adds value. The selected skill set is thin:

- context interpretation and domain selection;
- durable-meaning review;
- scoped evidence interpretation;
- governance authoring;
- architecture compliance review.

A skill may instruct an agent to call `invariant`, but it must not duplicate CLI mechanics or
reimplement the lifecycle. Skills must be independently useful and must not hash or import each
other as freshness dependencies.

Repository-local semantic prose remains optional reference material. Source-tree test adapters may
invoke the package, but they are not distributed as the application and cannot be imported by the
mechanics or lifecycle layers.

## 16. Safety and authority

- Read-only inspection needs no special authority.
- Explicit CLI mutation affects only targets named by the invocation.
- Remote publication defaults to off and requires accepted tracked configuration to opt in.
- The CLI never creates, selects, or changes a remote or upstream.
- An enabled push targets only the integration branch's existing upstream and names the exact
  verified commit as its source.
- Missing upstream configuration blocks before local landing. A remote rejection occurs after local
  landing and cannot roll that verified commit back.
- Ref updates use compare-and-swap against a captured old value.
- Untracked files that would be overwritten block synchronization.
- Failed verification never advances a ref.
- `authority: agent` does not authorize external or destructive effects.
- `execution: auto` does not bypass semantic gates or mechanical checks.

## 17. Implementation architecture

Invariant is a standard `src`-layout Python distribution built with `uv_build`:

```text
src/invariant/
  semantics/   typed envelopes plus free-form stage guidance
  mechanics/   deterministic repository operations
  lifecycle/   the resumable task state machine
  cli/         argument parsing and text/JSON presentation
```

Dependency direction is CLI → lifecycle → mechanics and semantics. Mechanics never imports
lifecycle, skill packages, or a host application. Semantics describes meaning but does not mutate
Git. Compatibility shell paths translate arguments into package calls and contain no policy.

The distribution is `invariant-cli`; its console entry point is `invariant`. Codex requires no
special binding beyond process execution and JSON. A future MCP or harness adapter must call the
same command contract rather than duplicate it.

Tracked governance remains version 1 unless an actual model change requires another version. The
version-one protocol uses only the Invariant namespace and does not translate earlier names.

## 18. Version-one acceptance criteria

The first CLI release is complete when:

- one installed `invariant` executable replaces direct package-relative script invocation;
- `invariant task begin` creates the receipt and isolated generated worktree without moving the
  integration checkout;
- `invariant task finish` recomputes reach, verifies the exact prospective tree, and atomically lands
  it;
- automatic and assisted execution preserve the same lifecycle and differ only in routine pauses;
- every read-only command supports stable JSON output;
- existing state validation, reach, audit freshness, coordination, and landing tests pass through the
  CLI;
- no context or verification command depends on a loaded skill;
- context mechanics do not depend on coordination runtime;
- semantic selections enter through explicit arguments or a versioned assessment document;
- canonical prose remains first-class while the semantic index supplies only identity, authority,
  applicability, revisit, verifier, relation, and supersession coordinates;
- lifecycle hooks return typed actions and never create a second task lifecycle;
- candidate reviews consume CLI-captured evidence instead of manually transcribing it;
- discoveries represent observations, basis, relevance, and broad resolutions without requiring a
  contract;
- exact-tree verification can run without updating a ref;
- atomic local landing remains available as an explicit command;
- routine managed work passes through receipts, generated branches, and atomic landing without
  unnecessary semantic or confirmation ceremony;
- a Codex task can use the CLI through shell execution without a custom Codex integration;
- another application can consume the same behavior through JSON without parsing prose;
- remote publication remains off by default and can target only the configured integration branch's
  existing upstream after verified local landing.

The governing design rule is:

> Semantics supplies meaning, mechanics proves repository facts, and lifecycle decides when to act.
