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

The core product philosophy is:

1. free-form agent reasoning for accuracy;
2. deterministic, inspectable state where reasoning becomes consequential;
3. near-zero user ceremony for routine work;
4. hard authority boundaries when an accepted promise is genuinely at risk.

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

The core CLI is a standalone local lifecycle application, but it is not an agent harness. Its
primary role is to be executed as a child process by a coding agent or another application. Direct
human use is limited to configuration, inspection, resolution support, and optional lifecycle
control—not repository investigation or implementation.

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
returns the task worktree plus typed lifecycle state and actions. Generated runtime paths remain an
implementation detail under the primary worktree's `.invariant/runtime/` namespace.

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
output. Invariant supplies the relevant guidance when it invokes an agent; initialization does not
copy lifecycle rules into persistent `AGENTS.md` or `CLAUDE.md` files.

### 4.3 Local-agent host and advanced harness

The installed `invariant` entry point provides a human host over the deterministic core. It can
start an already-installed, locally authenticated Codex or Claude Code process and keep the model
inside the same governed task lifecycle. The core CLI, lifecycle, mechanics, semantics, and protocol
layers do not import the host, provider SDKs, or provider authentication code.

The public host separates four states:

- a machine connection means a native executable is installed and reports an authenticated local
  session;
- the machine default chooses the first harness tried by clones without a local preference;
- a clone-local preference of `auto`, `codex`, or `claude`, kept under `.invariant/runtime/` and
  never committed, overrides the machine default for one checkout.

`invariant connect` inspects connections and reports the machine default without model invocation.
Only the global `invariant connect PROVIDER` and `invariant connect --default PROVIDER` forms
delegate login to the native CLI when needed. The latter also switches the machine default. The
local `init --agent PROVIDER` and `set harness PROVIDER` commands record that clone-local
preference without changing the machine-wide connection or the tracked configuration. Invariant never reads or stores credentials. `auto`
deterministically prefers the authenticated machine default, then the other supported harness. A
named provider does not fall back.

The human-facing model operations are:

- `ask PROMPT`, a fresh read-only repository question;
- `start [PROMPT]`, a persistent read-only conversation that may route implementation requests
  through `change` when its local runtime mode permits;
- `change PROMPT`, a generated task ID plus isolated provider write, candidate commit, evidence,
  verification, typed action resolution, and local landing; and
- `establish`, a generated governance task ID plus read-only audit, deterministic audit persistence,
  unambiguous projection, verification, and local landing.

Each accepts `--using` as an override. The one-shot operations accept `--dry-run` as a no-invocation
preview. `change` and `establish` accept `--id` for automation; human callers never need to invent a
task or action ID. Provider invocation is restricted to those explicit model-backed operations.
Status, settings, and connection inspection never invoke a model. Initialization's repository seeding
is deterministic; its final interactive yes-or-no choice may continue into the distinct model-backed
establishment operation after initialization completes.

The distribution retains `invariant-agent` as a separate advanced host-side executable. This bridge
reads a typed request from the core CLI, starts a provider in the task worktree, and sends the
structured result back through the protocol. It:

- discovers `codex` and `claude` on `PATH`, accepts explicit `INVARIANT_CODEX` and
  `INVARIANT_CLAUDE` executable paths, opportunistically discovers the Codex executable bundled in
  the macOS ChatGPT app, and relies on each executable's existing local authentication and account
  configuration;
- exposes `ask --using PROVIDER PROMPT` for an immediate, one-shot, read-only repository answer,
  with `--dry-run` as an explicit preview;
- exposes `resolve TASK --using PROVIDER` as an ergonomic advanced surface, infers the action when
  exactly one is pending, and requires `--action ACTION_ID` only when selection is ambiguous;
- defaults state-changing resolution and governance operations to a non-mutating preview and
  requires `--apply` before model invocation or submission;
- runs a fresh, non-persistent, read-only provider session in the selected repository or the exact
  managed task worktree;
- supplies the action's versioned JSON schema to the provider and preserves causal constants such
  as goal digest, candidate tree, review id, and attribution;
- records provider session identity, token/cost metadata when supplied, and a response digest in its
  result without storing credentials or conversation state;
- stamps `authority` and `review_mode` on every review it submits from how it dispatched the
  action, recording `independent` only when invoked with `--independent` because the host routed
  the action away from the candidate's author; the public `change` command reviews with the
  authoring provider and therefore records `self-attested`; and
- treats provider output as untrusted input which the existing core command validates before any
  lifecycle transition.

Codex is invoked through non-interactive `codex exec` with an ephemeral read-only sandbox, ignored
user configuration and execution rules, disabled hooks and MCP servers, and a schema-bound final
output. Claude Code is invoked through print mode with restricted mode, plan permissions,
repository-reading tools only, denied MCP tools, no session persistence, and a JSON schema. Provider
eligibility, quotas, and billing remain properties of the locally authenticated provider CLI; the
harness neither proxies nor resells model access.

Resumed Codex turns restate the read-only sandbox through configuration rather than inheriting
it from the first turn.

The source-write phase is separate. Codex runs ephemerally with `workspace-write`, disabled hooks
and MCP servers, and no inherited user configuration. Claude Code runs in bare print mode with
accepted repository edits, an explicit local tool set, denied MCP tools, denied shell access to
commits, publication, ref movement, worktrees, and the `invariant` executables, and no session
persistence.
The task worktree is the process working directory, and the host prompt forbids commits,
publication, external effects, and Invariant runtime changes. The host—not the provider—creates the
candidate commit and sends it through core evidence, review, verification, and landing.

The advanced binding owns one-shot repository questions, governance audit generation, and resolution
of pending typed lifecycle actions. The explicit
`task respond TASK ACTION --using PROVIDER [--apply]` form remains available as an automation
contract. Source changes are owned by the public host's distinct write phase, not by typed semantic
workers. Both surfaces consume the same deterministic core protocol.

## 5. State and authority

Tracked repository state remains:

```text
.invariant/config.yml
.invariant/SEMANTICS.yml
.invariant/DOMAINS.yml
.invariant/CONTRACTS.yml
.invariant/SOURCES.yml
.invariant/sources/<material>
.invariant/audits/<id>.yml
.invariant/discoveries/<id>.yml
```

Initialization creates the configuration only. Domain and contract registries are created only when
accepted records exist; bootstrap does not manufacture empty semantic authority or write provider
instruction files.

Generated local state is shared by linked worktrees and self-ignored at its root:

```text
.invariant/runtime/briefs/<task-id>.yml
.invariant/runtime/tasks/<task-id>/...
.invariant/runtime/history/tasks/<task-id>/<landed-commit>/...
.invariant/runtime/verifications/<evidence-id>.*
.invariant/runtime/plans/<id>.yml
.invariant/runtime/leases/<unit>.yml
.invariant/runtime/worktrees/<task-id>-<nonce>/...
```

This runtime is outside repository history, but not scattered outside the Invariant namespace.
Active task state is cleaned on completion; the completed argument archive and reusable verifier
receipts remain inspectable until an explicit `invariant coordinate runtime clean --apply`.

The standing of each object is:

| Object | Standing | Lifetime |
|---|---|---|
| Semantic record and canonical prose | accepted interpretation | repository history |
| Domain and contract projections | accepted authority | repository history |
| Source registration and repository-held source material | evidence only | repository history |
| Audit, discovery | evidence only | repository history |
| Intent brief and candidate reviews | task-local semantic argument | ignored archive until explicit cleanup |
| Plan, lease | coordination only | active work |
| Active receipt | cache integrity only | active task |
| Git tree and commit | causal implementation fact | repository history |
| Verification result | reproducible observation for one exact tree | ignored cache/archive until explicit cleanup |

Only accepted governance binds future work. Evidence can motivate governance but cannot become
authority without explicit adoption.

### 5.1 Grounding sources

A grounding source is attributable evidence attached to an existing semantic scope. The public
addition grammar has exactly two exclusive pairs:

```text
invariant source add
  (--url <absolute-http(s)-url> | --path <path-relative-to-.invariant>)
  (--scope <domain-or-contract> | --repo)
```

Paths must be regular files beneath `.invariant/sources/`; traversal, absolute paths, runtime
paths, and escaping symlinks are rejected. Exact scopes use lowercase `domain:<id>` or
`contract:<id>` locators. Non-locator scope descriptions are resolved by a read-only agent against
the accepted domain and contract catalog, never against the source content. The original phrase
and normalized locator are both retained. `--repo` is repository-wide applicability, not a
machine-global setting.

The source ID is deterministically derived from its canonical origin. Adding a source writes only
the source index and, for a path origin, the named source material. It runs as a `no-record` task
through the ordinary isolated candidate, exact-tree validation, and atomic local landing path. It
cannot create or modify architecture, domains, contracts, decisions, or constraints. Model prompts
label registered sources as untrusted evidence; source content is never treated as instructions or
semantic authority.

One logical Invariant kernel is attached to each Git common directory. Commands resolve the Git
top-level first and use only `<worktree-root>/.invariant`; they never select the nearest nested
`.invariant`. Tracked nested Invariant state inside the same Git repository is invalid. Linked
worktrees share runtime through the primary worktree. A genuine nested Git repository or submodule
has a distinct Git identity, kernel, verification boundary, and landing lifecycle.

## 6. Configuration

Tracked repository configuration remains small:

```yaml
version: 1
authority: agent
execution: auto
integration_branch: auto
push_remote: off
adapters:
  intent_brief: off
```

Provider selection is deliberately absent from tracked configuration: which coding agent is
installed and signed in is a fact about a person and a machine, not about the repository, so a
clone must never fail because another machine's choice was committed. The host resolves the
provider from `--using`, then the clone-local preference, then the machine default. `auto`
prefers the authenticated machine default and then the other supported harness. None of this is
authentication material, semantic authority, or permission to invoke a model outside an explicit
model-backed command.

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
Reach and authority are recomputed against the exact prospective tree. If that exact check newly
discovers an open or gated transition, accepted agent authority supplies the internal acknowledgement
and continues automatically; human authority emits a review action. A public caller is never asked to
provide the protocol's `allow_open` field or an equivalent flag.

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

Ordinary `test:` verifier locators require no configuration. The verifier resolves execution from
the exact candidate: Python tests locate the nearest `pyproject.toml`; shell tests in a locked uv
project execute through `uv run --frozen`; standalone shell tests execute through POSIX `sh`.
Automatic reuse is enabled only for a locked environment and the same exact candidate tree.
Resolved commands, working directories, timeouts, environment fingerprints, cache decisions, and
logs are evidence recorded under ignored runtime state, not governance. Named `runner:` locators
remain an expert escape hatch for a toolchain that cannot be inferred and must opt into reuse.
Every verifier runs under a time limit: `verification.timeout` (default 300 seconds) applies to
each inferred locator and to any runner that declares no limit of its own, and a verifier that
exceeds it fails the candidate rather than holding the landing open.

Before initialization, repository authority, execution, and landing settings are undefined. Managed
commands stop with `not_initialized` and point to `invariant init`; only help, version reporting,
provider connection, and initialization remain available. Initialization persists
`authority: agent`, `execution: auto`, `integration_branch: auto`, `push_remote: off`, and no enabled
adapters unless the user selects otherwise. Automatic execution is the ergonomic default; it does not
remove briefing, branch isolation, exact-tree verification, or atomic landing. Neither execution mode
weakens validation or grants external authority.

`invariant init` is the repository bootstrap. Interactive invocation explains each setting and uses
arrow-key radio selection; only a named integration branch requires free-form typing. `--defaults`
selects every safe repository default without the policy questionnaire. Initialization attempts the
named provider, or the machine-default provider followed by the other supported provider for `auto`.
Each failed native connection is reported as a warning and skipped; it does not fail repository setup
or prevent the next connection attempt. It creates `.invariant/config.yml` and does not inspect, create,
or modify provider instruction files. After deterministic setup, text-mode interactive initialization
asks one final yes-or-no question about running `invariant establish`.
Choosing no reports that command without requiring a user-authored prompt. Non-interactive `--defaults`
also initializes only and reports the separate establishment command. `init` has no establishment
control flags. Before writing repository files it proves that
Git provides the linked-worktree and `merge-tree --write-tree` capabilities used by the lifecycle.
It reports provider connection state but never changes machine-wide sign-in. Existing unrelated
agent instructions are outside initialization's scope. Managed task creation also requires the
initialized configuration to exist in the accepted integration commit, so every linked worktree begins
with the authority that governs it. A clean setup commit carries the no-record lifecycle attestation and
becomes the coverage baseline; establishment remains the separate operation that creates durable
repository records.

If `.invariant/config.yml` already resolves as a complete configuration, text-mode initialization
warns before connection attempts or policy questions. Keeping the configuration is the safe default
and makes no changes. Explicit replacement runs the normal setup and replaces the complete settings
document; `invariant set <key> <value>` is the path for changing one setting. Machine-readable
initialization never replaces an existing configuration implicitly.

`invariant config show` displays configured and resolved values after initialization.
`invariant config init` remains the lower-level configuration-only initializer.
`invariant config set <key> <value>` updates one validated setting atomically. The settable keys are
`authority`, `execution`, `integration_branch`, `push_remote`, and `adapters.intent_brief`.
Version `1` is the configuration schema marker, not an operational setting.

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

Internally, the domain document is parsed once into an immutable `DomainIndex`. Each `Domain`
retains the responsibility prose without interpreting it, while the index owns identity,
parent traversal, deterministic ordering, and round-trip serialization. Mechanics consumes that
typed projection instead of independently interpreting domain dictionaries.

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
one substantive summary, unresolved `candidate_defects`, and any non-blocking
`retained_discoveries`. It does not manually restate one result per
sentence or transcribe evidence the CLI already owns. A changed candidate, goal, brief, or adapter
implementation invalidates the review.

## 8. CLI contract

The executable is named `invariant`. Its primary human surface is:

```text
LOCAL   invariant init [--defaults] [--agent <auto|codex|claude>]
GLOBAL  invariant connect [codex|claude] [--default <codex|claude>]
LOCAL   invariant ask [--using <provider>] [--dry-run] <prompt>
LOCAL   invariant start [--using <provider>] [--mode <ask|change>] [<prompt>]
LOCAL   invariant change [--using <provider>] [--id <change-id>] [--dry-run] <prompt>
LOCAL   invariant establish [--using <provider>] [--id <establishment-id>] [--dry-run]
LOCAL   invariant status [<change-id>]
LOCAL   invariant settings
LOCAL   invariant set <key> <value>
GLOBAL  invariant help protocol
```

`invariant connect` reports the machine-default harness. `invariant connect --default PROVIDER`
establishes that native connection and switches the machine default. A clone without a local
preference follows it; `invariant set harness PROVIDER` records a clone-local override under
`.invariant/runtime/`, which is self-ignored and never committed.

`invariant start` owns one foreground console and one or more in-memory conversation handles until
EOF, `:exit`, or Ctrl-C. Its default local runtime mode is `ask`. `change` mode may answer or route a
self-contained request into the ordinary public change lifecycle. The conversation process never
writes the repository directly: every implementation still enters isolated task execution,
candidate verification, and compare-and-swap landing. `:new`, `:sessions`, and `:switch` manage
conversations inside a console; starting another console never terminates an existing one.

Lifecycle and mechanical commands are composable and non-interactive. Repository bootstrap is the
deliberate exception: `invariant init` is interactive, while `invariant init --defaults` skips the
policy questionnaire. When terminal input is available, either form offers one final yes-or-no choice
to establish records after deterministic setup has completed. Non-interactive `--defaults` initializes
only and reports `invariant establish` as the next step. On an initially clean repository the host
commits bootstrap files locally before establishment; when
unrelated work is already present it leaves initialization uncommitted and reports that precondition
before the first establishment or change.
Repeated text-mode initialization first warns that continuation replaces the complete configuration;
it proceeds only after an explicit replacement choice.

At the protocol layer, a task ID is a caller-chosen, repository-local identifier for one managed
change. It begins with an alphanumeric character, may contain alphanumerics, `.`, `_`, and `-`, and
connects the task's goal, receipt, generated branch, verification, and landing. For example,
`fix-job-recovery` is the task ID in:

```bash
invariant task begin fix-job-recovery --goal "Restore active jobs after restart"
```

The advanced protocol command groups are:

```text
invariant init [--defaults]
invariant status [<task-id>]
invariant governance begin <task-id>
invariant governance audit-save <task-id> --input <findings-file>
invariant governance adopt <task-id> <--all-ready|--finding <id>...>
invariant governance project <task-id> [--input <adoption-manifest>]
invariant governance coverage <task-id>
invariant governance projection <schema|example>
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
invariant task action <task-id> <action-id>
invariant task evidence <task-id> [<evidence-id>]
invariant task continue <task-id> [--apply]
invariant task reconcile <task-id>
invariant task invalidate <task-id> [--discard]
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

The `task` group is the underlying lifecycle interface. These groups expose inspectable mechanical
capabilities for hosts, diagnostics, CI, and recovery; they do not provide an alternate path around
lifecycle invariants. The installed package owns the implementation and never invokes
package-relative skill scripts.

Two commands exist only for recovery. `task reconcile` repairs a task whose landing outran its
bookkeeping: it replays an integration checkout sync that a crash interrupted after the ref moved,
and archives a task whose unit trailer already reached the integration branch. `task invalidate`
abandons a task and removes its generated worktree and branch; it refuses to drop uncommitted or
unlanded work unless `--discard` is given. `coordinate runtime clean` reports generated work that
no active receipt references and removes it with `--apply`.

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
Architecture acknowledgements and open or gated authority are never taken from the assessment
alone: whenever the candidate affects accepted meaning, landing requires the candidate review
action to have been accepted for that exact tree, and an assessment supplied without it is
refused as `semantic_review_required`.
`task finish` owns assessment preparation. If no semantic judgment remains, it proceeds in the same
command. Otherwise it returns compact action references plus the exact candidate tree and captured
evidence IDs. `task action` retrieves affected semantics, inferred governance, the response schema,
and other action-specific context. `task assessment prepare` exposes the lower-level assessment for
diagnostics; normal hosts do not edit it.

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
candidate_defects: []
retained_discoveries: []
```

`invariant task intent-brief schema` exposes both adapter response shapes.

### 8.2 Structured output

Every command supports `--format text|json`, placed before or after the subcommand. Text is for
direct use; JSON is the application integration contract. JSON is compact by default and never
duplicates its human rendering; `--verbose` adds that rendering explicitly for diagnostics.

The `invariant`, protocol, and `invariant-agent` surfaces all emit the same envelope, and an
exit status crosses the harness boundary unchanged: a blocked core result stays exit `1` when
reported through `invariant-agent` or `invariant change`. An unexpected internal failure still
produces the envelope, with diagnostic code `internal_error` and exit `2`.

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
      "boundary": "no-record",
      "actions": [
        {
          "id": "core:candidate-review",
          "adapter": "core",
          "phase": "candidate.evidenced",
          "kind": "review_semantics",
          "blocking": true,
          "schema_id": "invariant://schemas/actions/review-semantics/v1"
        }
      ],
      "assurance": {
        "structural": {"status": "passed"},
        "behavioral": {"status": "not_required"},
        "semantic": {"status": "pending"}
      },
      "completion": {"commit": ""}
    },
    "candidate": {"tree": "<tree>", "evidence_ids": ["state:<id>"]}
  },
  "diagnostics": []
}
```

`outcome` distinguishes completed work, work ready for implementation, input suspension, and
assisted approval from actual failures. Stable diagnostic codes carry changed governance, stale
evidence, verification failure, conflict, or concurrent ref movement. Applications must use fields,
action IDs, and schemas—not parse human prose or inspect runtime files.
Public lifecycle errors name the retained change, summarize the blocking condition and recovery
state, and expose one public resume or inspection command. Low-level repair flags such as
`--reviewed` are protocol inputs produced by candidate-bound review, not user-facing recovery steps.
Read-only context commands serialize typed domain, reach, affected-record, review, and verifier
data directly; their JSON is not reconstructed by parsing the text rendering.
The default task result is delta-oriented: action schemas are expanded by `task action`, while
captured observations are listed or retrieved by `task evidence`. This keeps the normal protocol
small without making its supporting material inaccessible.

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

Each persisted action contains a stable ID, owner, phase, kind, human prompt, JSON Schema, blocking
flag, and candidate-specific context. Normal lifecycle output returns only its stable reference;
`task action <task> <id>` expands the prompt, schema, and context on demand. `task respond` resolves
exactly one ID. Adapter response files are transported through the CLI and stored privately; they
are never accepted governance merely because an adapter produced them.

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
8. A semantic review separates unresolved `candidate_defects` from non-blocking
   `retained_discoveries`. `review_mode` is `self-attested` unless a host actually dispatches the
   action to an independent reviewer; Invariant records this provenance but does not invent it.

There is intentionally no blocking post-update hook: after compare-and-swap succeeds, an optional
integration must not retroactively make the local landing ambiguous. Notifications or publication
beyond the separately configured upstream push belong to the host.

### 8.4 Output discipline

- Standard output contains only the selected result format.
- Successful lifecycle output is a state delta; full status, actions, and evidence are fetched by
  their dedicated read APIs.
- Successful verifier output is retained in ignored local logs and summarized rather than
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

An audit finding may carry complete `records` projections when the evidence-to-record mapping is
unambiguous. For selected findings, `governance project` materializes those projections and runs
structural validation. Findings without a complete projection remain `unresolved` in the generated
adoption draft; the author edits only those mappings to name records, a retained discovery, or an
explicit deferral. `governance coverage` maps every selected finding to its disposition. The CLI
projects and validates accepted meaning from the audit; it does not infer missing semantic content.

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
candidate always invalidates that evidence. Active receipts and logs live under self-ignored
`.invariant/runtime/`. On successful landing, the task receipt, evidence, brief, reviews, and a stable
`summary.yml` are archived under `.invariant/runtime/history/tasks/<task>/<landed-commit>/`. The active
receipt disappears, but `task status`, `governance status`, and `task evidence` resolve the latest
completed archive. The summary records initial and final boundary dispositions, governance audit
and finding coverage, landing commit, candidate tree, and structural, behavioral, and semantic
assurance separately. Reach, semantic
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
6. rebuilds and re-verifies routine candidates when concurrent landings move the target, while
   preserving exact-tree review boundaries; and
7. stops only for missing semantic authority, failed checks, conflict, movement that invalidates
   reviewed evidence, persistent movement, or unauthorized external effects.

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
  frontend.py  human command surface and local-provider orchestration
  protocol.py  stable cross-layer values for stages, outcomes, reach, boundaries, and evidence
  semantics/   typed envelopes plus free-form stage guidance
  mechanics/   deterministic repository operations
  lifecycle/   the resumable task state machine
  cli/         argument parsing and text/JSON presentation
  harness/     optional outer-process bindings to locally authenticated coding agents
```

Dependency direction is CLI → lifecycle → mechanics and semantics. Mechanics never imports
lifecycle, skill packages, or a host application. Semantics describes meaning but does not mutate
Git. `protocol.py` contains data types only—no policy, I/O, or repository operations—so layers can
exchange discriminated values without importing each other. Compatibility shell paths translate
arguments into package calls and contain no policy.

The distribution is `invariant-cli`; its console entry point is `invariant`, with the advanced
`invariant-agent` host executable in the same package. `invariant` routes advanced commands directly
to the core CLI and implements model-backed human operations outside the core dependency layers.
Any future MCP or richer harness adapter must call the same command contract rather than duplicate
it.

Tracked governance remains version 1 unless an actual model change requires another version. The
version-one protocol uses only the Invariant namespace and does not translate earlier names.

## 18. Version-one acceptance criteria

The first CLI release is complete when:

- one installed `invariant` executable replaces direct package-relative script invocation;
- machine connection, repository provider selection, and instruction-file setup remain separate;
- a human can ask, establish repository records, and land a managed change without supplying task or action
  IDs;
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
- the optional harness can resolve the same schema-bound read-only action through either a locally
  authenticated Codex or Claude Code process without introducing a core-to-harness dependency;
- another application can consume the same behavior through JSON without parsing prose;
- remote publication remains off by default and can target only the configured integration branch's
  existing upstream after verified local landing.

The governing design rule is:

> Semantics supplies meaning, mechanics proves repository facts, and lifecycle decides when to act.
