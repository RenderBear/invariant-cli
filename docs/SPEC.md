# Invariant — implementation design of record

This document specifies the reference implementation of [protocol version 1](../protocol/protocol.md).
The protocol defines the implementation-independent contract; this file defines the Python package,
Git representation, compiler, recommendation engine, capability gateway, MCP tools, CLI, and local
execution mechanics. Where they disagree, the protocol governs and this document is wrong.

The implementation and all tracked state use protocol version 1.

Invariant implements a protocol that builds the governance layer for complex agentic work:

```text
governance layer = semantic kernel + Git-grounded lifecycle
```

The semantic kernel binds supplied intent, accepted meaning, resolution authority, and closed
consequences. The lifecycle grounds every consequential decision in durable Git objects, isolated
work, exact evidence, and atomic integration. Neither half is presented as sufficient by itself.

> An intent supplier says what state is desired. A harness runs workers. Invariant decides the
> admissible work shape, grants bounded resolution or execution capabilities, verifies the exact
> result, and records why it was allowed.

“Governance” here is operational. Accepted meaning must affect context, review, verification,
parallel ordering, capability issuance, or landing. A record that has no possible protocol effect is
documentation or evidence, not governance.

---

## 1. Product boundary

### 1.1 Goals

The reference implementation answers these questions for every requested change:

1. Which accepted repository meaning applies to this supplied intent and its actual result?
2. Which consequences does that meaning require or prohibit?
3. Should the change remain one unit, or what is the maximum admissible parallel frontier?
4. Which narrowly scoped capabilities may be issued to which worker attempt?
5. What work, evidence, and review produced this exact candidate tree?
6. May the candidate move the integration ref or publish its landed commit?
7. Can another harness resume correctly after processes, sessions, or substantial time have passed?

The answer must be deterministic wherever repository facts suffice, typed wherever judgment is
required, causally bound to Git objects, and durable enough to reconstruct without a transcript.

### 1.2 Non-goals

Invariant does not:

- choose the harness's models, worker count, machines, retry policy, or message transport;
- run implementation workers or own their conversation state;
- expose a generic shell, arbitrary Git command, network client, or credential proxy;
- infer permission from free-form prose, `AGENTS.md`, model confidence, or tool annotations;
- claim hard containment when a worker retains an out-of-band path;
- prove that an accepted architectural decision is wise;
- turn a verifier into proof of the entire prose assertion;
- replace Git hosting, CI, identity providers, or an operating-system sandbox; or
- make active change refs portable through an ordinary clone without explicit export.

### 1.3 The product surfaces

There is one application service with two transports:

- **MCP is the harness-facing capability gateway.** It is repository-bound at process startup and
  exposes only typed operations.
- **The CLI is the operator, inspection, and recovery surface.** It calls the same application
  service and is useful when no MCP host is present.

Neither transport is authoritative. Git-backed governance and ledgers are authoritative. The MCP
server does not shell out to the CLI, and the CLI does not reimplement MCP behavior.

---

## 2. Execution, authority, and containment

The implementation keeps execution and authority as orthogonal types:

- **execution** is access to an operational consequence and is represented by an execution
  capability; and
- **authority** is the right to supply intent or resolve one semantic question. Intent supply is an
  attributable input. Resolution is represented by an action-bound resolution capability.

Models, tools, and harnesses do not gain authority from their ability to execute. An
`intent.resolve` token may be included in a model adapter request only when accepted policy permits
delegation for that exact action. The adapter never receives a standing authority mode.

The application evaluates three different properties for consequential operations:

1. **Intent:** the request is bounded by an attributable desired-state statement.
2. **Authorization:** accepted policy and governance permit this resolution or execution
   consequence.
3. **Containment:** for execution capabilities, the actor has no alternative path around the
   gateway for this consequence.

Authorization is implemented by the current gateway. Containment is reported per execution capability and may be
`advisory` until a concrete containment provider proves otherwise. The UI and structured output must
never collapse those properties into one “safe” flag.

A containment provider is host-local configuration, not repository authority. It reports the
mechanism and observations that justify `managed`, for example:

- a worker sandbox cannot write the integration common directory;
- only the Invariant service owns the remote credential;
- worker network access cannot reach the Git remote; or
- a delegated filesystem handle exposes only one generated worktree.

The first implementation includes `uncontained`, which always reports `advisory`. Additional
providers plug into the gateway behind a fixed interface. A harness assertion about its own sandbox
is recorded as `harness:` provenance but does not by itself upgrade enforcement.

Grant tokens are bearer secrets. The service generates 256 random bits, returns the token exactly
once, and stores only its SHA-256 digest in the ledger. Tokens never appear in text rendering, logs,
commit messages, handoff capsules, or verification artifacts. A resumed harness revokes abandoned
live grants and requests new ones.

---

## 3. Semantics {#semantics}

### 3.1 Record model

Records are immutable typed values loaded from one exact Git tree. The package defines:

```text
SemanticRecord
DomainRecord
ContractRecord
ConstraintRecord
Directive
RecordDigest
GovernanceSelection
ObligationSet
```

Unknown closed fields and directive kinds are rejected. Open `relations` and `facets` are retained
as data but never consulted by authorization or planning mechanics.

Record filenames equal their ids. IDs are unique per kind. Every locator in a closed record or
directive field resolves against the exact selected tree: record locators name existing records,
repository paths and prefixes are tracked, audit ids name saved audits, verifier paths are files,
and interfaces are declared by a domain. Architecture locators resolve to headings carrying an
explicit `{#stable-anchor}`. The digest serializer normalizes mappings and sets, preserves ordered
prose where order matters, reads exact canonical sections from the selected tree, and hashes the
resulting UTF-8 bytes.

The v1 schema is direct:

- semantic records carry `directives`, and `applies_to` may name `capability:<name>`;
- domains carry `scope` and `interfaces` as planning and selection coordinates;
- contracts define mandatory `between`, `surfaces`, `architecture`, and `verifies`;
- constraints carry `directives` and require at least one directive or verifier;
- `applies_to` uses typed locators such as `domain:<id>`; and
- every tracked configuration and record uses `version: 1`.

### 3.2 Selection

Selection takes an exact tree plus intent-derived and observed reach:

```text
paths + interfaces + domains + contracts + capabilities + governed material
    -> direct record intersection
    -> domain parents and named contracts
    -> semantic revisit dependencies
    -> canonical sections and defining material
    -> stable ordered GovernanceSelection
```

Pre-work selection uses declared claims and semantic planner output. A capability request also
selects every active record whose `applies_to` intersects `capability:<name>`; a publication rule
therefore cannot disappear merely because publication changes no source path. Candidate selection
uses the actual Git diff and overrides omissions in the declaration. Selection returns each reason,
so an operator can ask why a record applied without asking a model to reconstruct the answer.

### 3.3 Normative compiler

The compiler is a pure function:

```text
compile(policy, selection, capability?, recommendation?, candidate?, containment?)
    -> ObligationSet
```

`ObligationSet` contains:

```yaml
sources: [policy:publication, record:constraint:no-publish@<digest>]
selected_context: [semantic:source-ownership]
denied_capabilities: [remote.publish]
required_resolution: {}
required_reviews: []
required_verifiers: [test:tests/test_remote_push.py]
serialize_on: []
parallel_limit: null
contract_edges: []
containment: {}
blocks: []
digest: <sha256>
```

The compiler applies the protocol precedence rules with no model call. It rejects contradictory
closed requirements and always includes source locators. A consequence without a source is an
internal error; a source without an applicable record digest is stale governance.

Every accepted record has intrinsic operational value:

- a semantic record selects canonical prose, attributable review, invalidation, verifiers, and
  directives;
- a domain supplies responsibility context and a planning boundary;
- a contract supplies provider/consumer ordering, mandatory verification, and independent review
  when its definition or provider implementation changes; and
- a constraint supplies a verifier, a directive, or both.

This is the implementation distinction from an instruction file. Prose still guides judgment, but
the compiler—not model memory—decides the closed consequences.

### 3.4 Semantic judgment

Some questions remain irreducibly semantic: whether a requested outcome crosses a responsibility
boundary, whether two units are meaningfully independent, whether an exact candidate preserves an
accepted interpretation, and whether a new record should be accepted.

These questions use typed actions. The application composes exact selected context, the semantic
planner or reviewer returns schema-bound assertions, and deterministic code validates identifiers,
claims, evidence, authority, and causal bindings. A semantic response can propose a recommendation
or satisfy a review obligation only when accompanied by a matching `intent.resolve` capability. It
cannot supply original intent, grant a capability, or mark a verifier passed.

The configured local provider is an adapter. Provider authentication, quota, and session ids stay
outside the repository. If no semantic provider is available, planning falls back to one unit and a
required semantic review becomes `needs_input`; it never becomes an implicit approval.

---

## 4. Mechanics {#mechanics}

### 4.1 Repository identity and capabilities

The application resolves:

- the Git common directory;
- the primary worktree;
- repository identity from the initial commit when present, otherwise a stored bootstrap nonce;
- integration target and exact head; and
- required Git features before mutation.

Required features are linked worktrees, `merge-tree --write-tree`, `commit-tree`, symbolic-ref and
upstream inspection, and compare-and-swap `update-ref`. Missing features fail before any ref or
worktree mutation.

Every public operation accepts an already bound `Repository` object. A repository path is resolved
only at CLI invocation or MCP server startup; lower layers never change repository based on request
data.

### 4.2 Git-backed ledger

`LedgerStore` represents one change at `refs/invariant/changes/<change-id>`. A ledger commit tree is:

```text
snapshot.yml
events/<sequence>-<event-id>.yml
```

`snapshot.yml` is the complete reducible state after the event. The event file contains the event
kind, canonical payload, actor, transport provenance, prior ledger commit, and event digest. The Git
commit's first parent is the prior ledger commit. Additional parents may anchor work or candidate
commits that would otherwise become unreachable.

The store writes blobs and trees, creates a commit with `git commit-tree`, then installs it with:

```text
git update-ref <ledger-ref> <new-ledger-commit> <expected-ledger-commit>
```

The initial event expects the zero oid. A losing concurrent append reloads and retries only when its
event remains valid against the new snapshot. Otherwise it returns
`concurrent_ledger_movement`. Event reduction is deterministic and validates sequence, parent,
event digest, allowed transition, and every referenced object on read.

Required event kinds are:

```text
change.opened
recommendation.requested | recommendation.recorded | recommendation.replaced
action.opened | action.responded
decision.recorded
grant.issued | grant.revoked | grant.consumed
attempt.created | attempt.submitted | attempt.rejected
unit.converged
candidate.constructed | candidate.evidenced | candidate.reviewed
landing.started | landing.completed | landing.reconciled
publication.completed | publication.failed
change.invalidated | work.discarded
```

Events are append-only. A later event changes current state without altering the event it supersedes.

### 4.3 Work and candidate refs

Each attempt receives:

```text
refs/invariant/work/<change>/<unit>/<attempt>
.invariant/runtime/worktrees/<change>-<unit>-<attempt>-<nonce>/
```

The ref is durable; the worktree is reconstructible. Worktree creation consumes
`worktree.create`, checks that the unit is in the current admissible frontier, establishes its exact
base, and records the path only after Git succeeds. The corresponding `worktree.write` grant names
the same ref and claims.

A submitted attempt must be clean and committed. Submission records its tip and actual changed
paths. Work outside declared claims rejects the submission but leaves the ref and worktree intact.

The aggregate candidate lives at `refs/invariant/candidates/<change>`. Units converge in a stable
topological order. Independent siblings use lexical unit id as the tie breaker. The candidate ref is
updated by compare-and-swap. A contract consumer's attempt base is the candidate tip after its sole
provider converged.

Convergence uses Git's in-core merge machinery and never checks the candidate into the integration
worktree. Conflicts return exact unit ids and paths and retain all refs.

### 4.4 Exact-tree verification

Verifier selection is compiled from policy, records, contracts, recommendation checks, and actual
reach. Each verifier runs against a detached materialization of the exact candidate tree, never the
mutable worker worktree. Evidence binds:

- candidate tree and captured integration base;
- verifier locator and resolved command identity;
- executable identity, working directory, environment fingerprint, and timeout;
- mechanics version, exit status, output digest, and reusable status.

Logs may be cached under ignored runtime. The ledger records the evidence id and durable metadata.
Evidence is reusable only when every bound field matches. Volatile runners are never reused.

### 4.5 Landing and remote publication

Landing consumes a single-use `integration.land` token and the exact candidate. It validates the
token immediately before creating and installing the attested commit. The target update uses
compare-and-swap against the expected head. Integration checkout synchronization happens only when
it cannot overwrite tracked edits or untracked paths.

An interrupted operation records `landing.started` before the ref move and
`landing.completed` after it. Reconciliation inspects the target, the attested commit, and the
expected transaction; it either completes bookkeeping or reports an exact conflict. It never
replays implementation or invents a second landing.

Publication is a separate post-landing operation. When tracked policy is `off`, the compiler denies
`remote.publish`. When `on`, the service resolves the integration branch's existing upstream before
local landing and later pushes `<landed-oid>:<upstream-ref>`. It never uses an implicit source,
creates a remote, changes upstream configuration, pushes another ref, force-pushes, or rolls back a
local landing after rejection.

---

## 5. Lifecycle {#lifecycle}

### 5.1 Change aggregate

A `Change` owns one or more work units rather than assuming one task maps to one worker:

```text
supplied intent and supplier
integration base
governance selection
one work recommendation
one or more units and attempts
zero or more concurrent admissible frontiers
one causally converged candidate
one final review and evidence set
at most one local landing
zero or one bounded publication result
```

A single-unit change uses exactly the same lifecycle as a parallel change. There is no shortcut that
writes directly to the integration checkout.

### 5.2 State machine

`ChangeService` reduces the ledger and computes stage rather than trusting a stored stage field.
Allowed transitions are:

```text
opened
  -> recommending
  -> ready
  -> executing <-> ready
  -> converging <-> executing
  -> evidencing
  -> awaiting-action <-> evidencing
  -> ready-to-land
  -> cleanup-required
  -> completed
```

`invalidated` is terminal for new work but does not erase refs. Any transition may return a typed
block, denial, stale result, or action without changing the preceding valid state.

### 5.3 Actions and reviews

The action store is part of the ledger. An expanded action contains:

```yaml
id: core:candidate-review:<digest>
kind: review-semantics
schema: invariant://v1/actions/review-semantics
blocking: true
bindings:
  change: <id>
  ledger: <commit>
  intent: <digest>
  supplier: <authority-locator>
  recommendation: <digest>
  candidate: <tree>
  governance: <selection-digest>
context: {}
```

The standard kinds are `recommend-work`, `resolve-intent`, `review-semantics`,
`review-independent`, `accept-governance`, and `supply-intent`. A response repeats every binding. A changed bound value
makes it stale. A delegated response consumes an action-bound `intent.resolve` token; a direct user
response records new supplied intent and does not pretend the user is a bearer-token executor.

Candidate review records `accepted`, `rejected`, or `uncertain`; summary; semantic disposition;
authority; mode; defects; and retained discoveries. Only `accepted` can satisfy an obligation.
`independent` is valid only when the recorded reviewer actor did not author a unit in the candidate.

### 5.4 Handoff and resume

`HandoffService` builds a canonical capsule from ledger state and Git objects. It contains no model
transcript and no bearer token. `change.resume` checks the supplied ledger head, reloads current
policy and governance, verifies all refs, revokes orphaned live grants, reconstructs missing
worktrees on demand, and returns the current admissible frontier or next action.

An old capsule yields `stale_handoff` plus the current ledger head and a safe read operation. It does
not roll state backward. A target descendant may allow candidate rebuilding; divergence, changed
governance, or changed contracts triggers new compilation and possibly recommendation replacement.

### 5.5 Retention and cleanup

Completion keeps the change ledger. Work and candidate refs remain until an explicit retention
operation proves their objects are reachable from the attested result or consumes a `work.discard`
grant. Invalidated, rejected, conflicting, and unlanded work is never cleaned automatically.

Runtime worktrees and logs may be removed as cache only after their exact ref and durable metadata
are present. Destructive cleanup names every ref and path; broad recursive targets, unresolved
variables, and repository-root deletion are prohibited.

---

## 6. Recommendation engine

### 6.1 Inputs and ownership

`RecommendationService` owns the work recommendation. Its inputs are the exact base, supplied intent, selected
governance context, domains, contracts, requested scope, retained relevant discoveries, host
capacity, and tracked maximum parallel width.

The semantic planner produces a typed proposal. It does not receive a worker-creation tool. The
deterministic validator either accepts and normalizes the proposal, returns repair diagnostics for
at most two semantic retries, or emits a conservative single unit. An invalid proposal never creates
a work ref or grant.

The harness may ask for a new recommendation or choose fewer workers. It may not supply its own
plan and label it an Invariant recommendation.

### 6.2 Validation

A recommendation is valid when:

- ids are unique and the unit count is between 1 and 32;
- every unit has a concrete objective and at least one typed claim;
- dependencies exist and form a directed acyclic graph;
- unordered units do not overlap path prefixes or identical interface claims;
- each changed contract has exactly one provider;
- every affected contract consumer transitively depends on its provider;
- consumer bases are marked `after-provider`;
- governance changes are isolated unless compiled directives say otherwise;
- `serialize` and `limit-parallelism` obligations are reflected; and
- every check locator resolves at the base or is explicitly marked candidate-created by its unit.

Path overlap uses normalized repository-relative prefixes, not string containment. `repo:a/b` and
`repo:a/bc` do not overlap. Interface and contract ids compare exactly.

### 6.3 Conflict graph and frontier

The validator constructs an undirected conflict graph in addition to dependency edges. For the
currently dependency-ready units it computes the exact largest independent set, bounded by the
tracked and host capacity. Plans are capped at 32 units; a deterministic bitset branch-and-bound
implementation is sufficient. Ties prefer the semantic planner's order, then lexical unit id.

The resulting cardinality is `maximum_parallelism`; the chosen set is `recommended_frontier`.
Live write grants remove conflicting nodes and available capacity. Completing or revoking an
attempt recomputes the frontier from ledger state.

The number is not a timeless claim about the whole repository. It is the greatest permitted live
set under this recommendation, its claims, accepted governance, current candidate, and current
grants. Actual diffs are checked before any unit can converge.

### 6.4 Recommendation replacement

A changed intent, base, selected record digest, contract surface, claim violation, or newly discovered
overlap invalidates the existing recommendation. Replacement retains prior recommendations and
records why the newer one governs. Completed unit work is reused only when its actual reach remains
within a unit in the replacement and its causal base remains valid.

---

## 7. Capability gateway

### 7.1 Capability classes and request evaluation

The gateway has two closed capability classes:

- `resolution`: `intent.resolve`; and
- `execution`: `worktree.create`, `worktree.write`, `verification.run`,
  `candidate.converge`, `integration.land`, `remote.publish`, `change.invalidate`, and
  `work.discard`.

Capability class is derived from the closed name, never supplied by a caller. Resolution grants bind
one typed action and carry no containment claim. Execution grants bind one operational resource and
report managed or advisory enforcement.

`CapabilityService.request` receives a closed `CapabilityRequest`, reduces the latest change ledger,
loads current governance, compiles obligations, checks containment, and calls the capability-specific
evaluator. Evaluation order is:

1. validate repository, actor, change, unit, attempt, and resource identity;
2. reject unknown capabilities and stale causal bindings;
3. apply policy ceiling and accumulated denial;
4. check recommendation, frontier, dependency, and conflicting grants;
5. check authority, review, verifier, and containment obligations;
6. record a denied, needs-authority, or stale decision; or
7. append decision and grant events atomically, then return the one-time token.

Every result includes `explain.sources` and `explain.obligations`. Text may summarize those fields;
clients never need to parse the summary.

### 7.2 Capability-specific rules

| Capability | Additional requirements |
|---|---|
| `intent.resolve` | exact pending action, supplied-intent digest, allowed actor; never delegated for policy changes |
| `worktree.create` | current recommendation and dependency-ready unit |
| `worktree.write` | existing attempt, admissible frontier, no conflicting live write grant |
| `verification.run` | selected verifier and exact candidate tree |
| `candidate.converge` | clean submitted attempt and actual claims within recommendation |
| `integration.land` | all obligations satisfied; exact candidate; single use |
| `remote.publish` | completed local landing, tracked opt-in, existing upstream; single use |
| `change.invalidate` | attributable actor and reason |
| `work.discard` | explicit authority and the canonical JSON array of exact retained refs; single use |

Ordinary reads do not append to the change ledger. Opening a change, recording Invariant's own
recommendation, recording a work submission, and requesting or revoking a grant are causally bound
operations but do not require a grant because they cannot accept meaning, execute a verifier,
create writable state, converge a candidate, move an integration ref, publish, or discard work.

### 7.3 Revocation and use

The ledger stores the token digest, not the token. Use hashes the supplied token, selects exactly one
live grant, re-evaluates causal invalidators, records `grant.consumed` before or in the same protected
transaction as the consequence, and refuses replay when `single_use`.

An intent or recommendation replacement revokes affected work grants. A candidate change revokes
resolution, verification, landing, and publication grants. Governance or target movement
marks affected grants stale; an explicit revocation event is appended on the next mutating resume.

### 7.4 Honest enforcement

The result for every decision contains:

```yaml
enforcement:
  posture: advisory
  provider: uncontained
  protected_resource: refs/heads/main
  evidence: []
```

No presentation layer may replace `advisory` with “blocked,” “prevented,” or “secure.” When a future
provider returns `managed`, its evidence identity and configuration digest enter the decision and
landing attestation.

---

## 8. Repository-bound MCP gateway

### 8.1 Process boundary

`invariant-mcp --repository <path>` starts a stdio server bound to one resolved Git common
directory. It accepts optional host-local principal and containment-provider configuration at
startup. No tool accepts a repository path, command string, shell fragment, executable, remote,
credential, or arbitrary environment.

The server calls `InvariantApplication` in-process. It retains no authoritative state in memory;
each call reloads or validates the relevant ref heads. Restarting the server cannot create a second
lifecycle or lose a change.

Protocol `denied`, `stale`, `blocked`, and `needs_input` results are successful MCP calls with typed
content. Exceptions in transport, schema decoding, or internal execution become MCP errors and a
protocol `failed` envelope when one can be produced.

### 8.2 Tool surface

The MCP server exposes exactly these tools:

| Tool | Mutation | Purpose |
|---|---|---|
| `invariant_state_validate` | no | validate policy, records, refs, and attested history |
| `invariant_governance_context` | no | select records and compile obligations for declared scope |
| `invariant_change_open` | yes | create the durable change ledger |
| `invariant_change_recommend` | yes | obtain and record Invariant's work recommendation |
| `invariant_change_inspect` | no | return reduced state, frontier, actions, grants, and assurance |
| `invariant_change_handoff` | no | return a canonical token-free handoff capsule |
| `invariant_change_resume` | yes | causally refresh and continue a handed-off change |
| `invariant_action_inspect` | no | expand one typed action |
| `invariant_action_respond` | yes | submit a causally bound response, consuming `intent.resolve` when delegated rather than directly supplied |
| `invariant_capability_request` | yes | record a decision and possibly return one bearer token |
| `invariant_capability_inspect` | no | inspect decision or redacted grant metadata |
| `invariant_capability_revoke` | yes | revoke one live grant |
| `invariant_work_create` | yes | consume a create grant and materialize an attempt worktree |
| `invariant_work_submit` | yes | record one clean exact work result and its actual reach |
| `invariant_candidate_converge` | yes | consume a converge grant and update the aggregate candidate |
| `invariant_candidate_evidence` | yes | consume verifier grants, capture evidence, and open any required review action |
| `invariant_integration_land` | yes | consume the exact landing grant and atomically update the target |
| `invariant_integration_reconcile` | yes | repair interrupted post-ref bookkeeping only |
| `invariant_publication_publish` | yes | consume a publish grant for the exact landed commit |
| `invariant_change_invalidate` | yes | stop future work without deletion |
| `invariant_work_discard` | destructive | consume explicit discard authority for named retained work |

MCP tool annotations describe read-only, destructive, and open-world behavior for host UX. They are
never consulted as authority.

Bearer tokens are returned only from `invariant_capability_request` and accepted only by the
specific consequence tool. Read responses always redact token material. Structured schemas reject
extra fields.

### 8.3 Principal and attribution

The stdio client is one `harness:<instance>` principal configured at startup or generated for that
server run. Calls name worker actors beneath it, but the transport principal attests who supplied
those names. Every event and projected actor-bearing value records both. Independent review requires
a distinct actor and a distinct transport principal from every candidate author; changing only the
asserted actor string is insufficient. Direct user authority is valid only when the asserted
`user:` locator equals the transport principal.

Remote MCP transport is outside the initial implementation. It cannot be added without an explicit
authentication and principal-binding design.

---

## 9. CLI and human interaction

The installed `invariant` entry point is a local human host over the application boundary. It owns
terminal presentation, provider processes, durable local conversations, project registration, and
the read-only web workspace. None of those objects is repository authority. Repository changes are
still performed by composing typed application operations and consuming the minimum exact grants.

The stable human surface is:

```text
invariant init [--defaults]
invariant status
invariant start [--session <id>] [--using codex|claude] [<prompt>]
invariant connect [codex|claude] [--default codex|claude]
invariant set <key> <value>
invariant serve [--port <port>] [--project <folder>]...
invariant-mcp --repository <path>
```

`init` is guided setup and commits only the deterministic bootstrap policy; `--defaults` skips the
questions. It also registers the repository in the per-user workspace. `status` joins exact
repository state with local sessions and reports governance record count, validation state, latest
audit, and audit staleness.

`start` creates or resumes one durable project session. `:new`, `:sessions`, and `:switch` navigate
sessions; `:agent` switches the provider for one session; `:status`, `:settings`, and `:set` expose
the same local host operations; `:accept` supplies direct user authority for one exact pending
governance candidate; and `:exit` releases live presence without deleting the transcript. Provider
handles and transcripts live in the per-user workspace and never become semantic evidence.

The conversational coordinator is read-only. When it classifies a user message as a write, the host
opens a durable change from the user's original message, obtains scoped worktree capabilities for a
provider-specific principal, runs the provider in the isolated worktree, commits the result itself,
verifies the exact candidate, obtains a distinct secondary review when compiled governance requires
one, and lands only through `integration.land`. Governance candidates pause for `:accept`.

`set harness` and `set mode` update clone-local host preferences. Every tracked setting is a
deterministic one-file governance candidate evaluated under the parent policy, directly accepted by
the invoking `user:cli`, attested, landed, and cleaned up. The command stages only the isolated
attempt; it never edits or asks the user to stage primary-worktree config. A transition to a
different integration branch is rejected until an atomic multi-ref transition is specified.

`serve` is one foreground, loopback-only service over the current user's workspace. It presents all explicitly
registered projects and their durable sessions, marks live consoles, and streams read-only project
snapshots over Server-Sent Events. The HTTP surface permits only GET and HEAD.

Text output leads with the decision and next permitted action. It distinguishes:

- `permitted and managed`;
- `permitted but advisory`;
- `needs authority`;
- `denied by <source>`;
- `stale; recomputation required`; and
- `mechanically blocked`.

JSON output is the protocol envelope unchanged. Exit codes follow the protocol.

---

## 10. Configuration and policy

Tracked configuration is deliberately small and makes authority structurally distinct from
execution:

```yaml
version: 1
authority:
  intent:
    suppliers: [user]
  resolution:
    delegation: secondary-agent
execution:
  transitions: auto
integration_branch: auto
publication: off
parallelism:
  maximum: auto
```

`authority.intent.suppliers` declares which attributable sources may originate change intent; v1
defaults to the user. Accepted records remain standing repository meaning regardless of this list.
`authority.resolution.delegation` is `secondary-agent` or `user`. `secondary-agent` allows the
kernel to issue `intent.resolve` for one eligible semantic action to a named model actor; `user`
requires new `user:` intent. Neither setting is an execution permission. Policy changes always
require direct user intent.

`execution.transitions` is `auto` or `assisted`. It is a host preference for compound operator
surfaces, not authorization and not an instruction to the kernel. The low-level CLI and MCP
operations always expose each decision and consequence explicitly.

`integration_branch` is `auto` or an existing local branch. `auto` resolves the primary worktree's
current branch when the change opens and then stores the exact ref in the ledger.

`publication` is `off` or `on`. Off compiles a denial. On only makes a capability request possible;
the existing-upstream and exact-commit checks still apply.

`parallelism.maximum` is `auto` or a positive integer. It is a policy ceiling, never a request to
create that many workers. Host capacity can narrow it per recommendation but cannot widen a numeric
policy value.

Provider preference, machine authentication, bearer tokens, containment provider, registered
projects, transcripts, and display preferences are host-local and never committed. Changing tracked
configuration uses a governed candidate. The parent policy evaluates that candidate, and review
requires `user:` authority.

---

## 11. Application contract

### 11.1 Service API

`InvariantApplication` accepts typed request objects and returns the v1 envelope. It owns
transaction boundaries and delegates to domain services. Transports do not call repositories,
planners, or mechanics directly.

The request families mirror the protocol:

```text
StateRequest
ContextRequest
ChangeRequest
ActionRequest
CapabilityRequest
WorkRequest
CandidateRequest
IntegrationRequest
PublicationRequest
```

Every mutating request carries `expected_ledger` and every ref-changing request also carries the
expected target or work ref. The application may fill an expected value only inside a compound
single-process operator command that read it immediately before the mutation.

### 11.2 Response envelope

```json
{
  "protocol": 1,
  "command": "capability.request",
  "status": "ok",
  "outcome": "denied",
  "result": {
    "decision": {
      "id": "decision:<digest>",
      "capability": "remote.publish",
      "enforcement": {"posture": "advisory", "provider": "uncontained"},
      "explain": {
        "sources": ["policy:publication"],
        "obligations": [],
        "reason": "Tracked publication policy is off."
      }
    }
  },
  "diagnostics": [{"code": "capability_denied", "message": "Remote publication is denied."}]
}
```

The `result` object is command-specific. Change results include change id, ledger head, stage,
recommendation digest, admissible frontier, pending actions, redacted grants, candidate tree,
assurance dimensions, and completion. Every causal id is a full oid or SHA-256, never an abbreviated
display hash in machine output.

### 11.3 Idempotency

Mutating requests include an `operation_id` chosen by the caller. The ledger records it with the
request digest. Repeating the same id and digest returns the recorded result; repeating the id with
different input fails `invalid_invocation`. This covers retries after an unknown transport outcome.

Grant consumption additionally uses the token digest and consequence identity. A completed
single-use consequence returns its recorded result instead of executing again.

### 11.4 Read discipline

Read operations do not update freshness files, create worktrees, append access events, renew grants,
or repair ledgers. Validation and inspection may be expensive but remain observational. Cached views
are acceptable only when their ref heads are included in the cache key and returned result.

---

## 12. Attestation and inspection

`AttestationService` produces deterministic landing trailers from ledger state. The complete
attestation may exceed practical commit-message size, so trailers contain stable digests and compact
repeated unit bindings while the retained ledger contains full explanations.

`state.validate` loads policy and records from the accepted integration commit, rejects mutable
worktree governance, then walks first-parent history from the commit that first introduced
`.invariant/config.yml`. It verifies:

- landing parent and candidate identity;
- change, supplied-intent, recommendation, and decision digests;
- unit result, actor, and transport-principal bindings;
- governance versions and required retirement markers;
- review and evidence digests;
- policy authority for governed policy changes; and
- coverage of out-of-band commits.

A copied or rewritten landing commit fails because its first parent and recomputed tree differ. A
missing local ledger does not invalidate an otherwise complete portable landing attestation, but it
reduces available explanatory detail and cannot support active handoff.

Inspection is projection, never reconstruction by prose. `change inspect` can answer:

- why the change was split or kept whole;
- which units may run now and which conflict;
- what each grant permits and what makes it stale;
- which accepted records caused each obligation;
- which exact work and candidate trees exist;
- who was recorded as author, reviewer, and authority;
- what remains before landing; and
- whether enforcement was managed or advisory.

---

## 13. Package architecture

The target package layout is:

```text
src/invariant/
  protocol.py                 closed enums, ids, request and result values
  application.py              one transaction-oriented application service
  governance/
    records.py                v1 record values and validation
    locators.py               exact-tree locator resolution
    selection.py              declared and actual governance reach
    compiler.py               deterministic obligation compilation
    authority.py              intent supply and resolution-capability validation
  ledger/
    events.py                 append-only event values and reducer
    store.py                  Git commit-tree and update-ref persistence
    handoff.py                capsule creation, validation, export, import
  planning/
    model.py                  recommendations, units, claims, edges
    recommend.py              semantic proposal orchestration and fallback
    validate.py               deterministic validation and conflict graph
    frontier.py               exact bounded admissible-frontier calculation
  gateway/
    capabilities.py           closed capability rules
    decisions.py              evaluation and explanations
    grants.py                 token issue, hash, use, revoke, staleness
    containment.py            posture-provider interface
  mechanics/
    git.py                    capability detection and exact object operations
    worktrees.py              isolated attempt materialization
    candidate.py              causal aggregate convergence
    verification.py           exact-tree evidence
    landing.py                attested commit and compare-and-swap landing
    publication.py            exact upstream publication
  lifecycle/
    changes.py                change state machine over ledger events
    actions.py                typed semantic and authority suspension
    recovery.py               resume, reconcile, invalidate, cleanup
  adapters/
    semantic_planner.py       bounded model-backed recommendation proposal
    semantic_review.py        exact-context review proposal
  mcp_server.py               repository-bound typed MCP transport
  frontend.py                 interactive human host and compact command surface
  conversation.py             read-only conversational classification and prompts
  surface.py                  compound human operations over the application boundary
  workspace.py                per-user project, session, transcript, and presence state
  observer.py                 read-only project snapshots and SSE polling
  host.py / dashboard.py      loopback workspace service and visual assets
  harness/                    native Codex and Claude connection and invocation adapters
  cli/style.py                terminal palette, wordmark, panels, turns, and motion
```

Dependency direction is:

```text
Human host / CLI / MCP
    -> application
        -> lifecycle / gateway / planning
            -> governance
            -> mechanics
                -> protocol values
```

Adapters depend on typed context and schemas and return proposals to the application. Governance and
mechanics never import adapters, MCP, CLI, presentation, skills, or provider SDKs. Mechanics never
decides semantic authority. Planning never creates workers. The gateway never runs arbitrary tools.

The distribution remains `invariant-cli` with `invariant` and `invariant-mcp` console entries.
Semantic adapters are optional application dependencies, not executables or authority surfaces.
They receive typed selected context and, when policy permits, an exact `intent.resolve` capability.

---

## 14. Failure and recovery rules

Failures are classified before presentation:

- **denied:** governance intentionally prohibits the capability;
- **needs authority:** a named attributable response is missing;
- **stale:** the request was valid for an older causal state;
- **blocked:** a repository fact such as conflict, dirty checkout, failed verifier, or missing Git
  capability prevents progress;
- **failed:** malformed input, corrupt durable state, transport failure, or internal error prevents a
  valid result.

No failure deletes work. Recovery may:

- reload and reduce the ledger;
- recreate a missing worktree from its work ref;
- rerun exact-tree evidence;
- replace a stale recommendation while retaining valid unit results;
- reissue a capability after revalidation;
- finish ledger bookkeeping for an already landed attested commit; or
- request explicit authority for invalidation or discard.

Recovery may not mark a check passed, accept a semantic review, broaden claims, change actor
provenance, or move a ref merely to make state consistent.

---

## 15. Verification strategy

Repository tests remain restricted to Git mechanics. The retained suite covers:

- Git capability detection before mutation;
- ledger and work refs surviving process and runtime loss;
- compare-and-swap ledger appends under concurrency;
- isolated parallel worktrees and exact attempt bases;
- contract-provider candidate ancestry;
- actual-diff claim enforcement as a Git reach property;
- exact candidate construction and evidence binding;
- atomic single landing under concurrent finish calls;
- recovery after the integration ref moved but ledger completion did not;
- dirty checkout and untracked collision preservation; and
- exact bounded remote publication with local landing retained after rejection.

Do not add tests for prose, prompt wording, presentation, semantic policy choices, private helpers,
MCP annotations, or documentation parity. Those are reviewed through typed schemas, static checks,
and implementation inspection. Git tests exercise the application service rather than shelling
through a presentation layer.

Build verification includes package import, wheel/sdist contents, `invariant --help`,
`invariant-mcp --help`, protocol-schema generation, `uv lock --check`, and `git diff --check`.

---

## 16. Acceptance criteria

The implementation is complete when:

- protocol responses report the literal version `1`;
- accepted records compile into source-attributed obligations through the closed directive
  vocabulary;
- every record kind has the intrinsic selection, planning, ordering, verification, review, or
  capability effects specified here;
- active changes, recommendations, actions, decisions, grants, work tips, and candidates survive
  deletion of `.invariant/runtime` and MCP restart;
- `change handoff` is sufficient for another harness to resume from the current Git-backed ledger;
- Invariant returns one unit for cohesive work and records a validated maximum admissible frontier
  for genuinely separable work;
- the harness can serialize or run the recommended frontier but cannot obtain simultaneous managed
  write grants outside it;
- contract providers converge before affected consumers receive attempt worktrees;
- actual unit diffs are checked against claims before convergence;
- every privileged operation consumes the correct causally current grant;
- decisions distinguish authorization from managed or advisory enforcement;
- MCP exposes only the repository-bound typed tools in §8.2 and calls the application in-process;
- the human CLI exposes interactive setup, durable multi-session chat, provider connection and
  switching, governed one-setting changes, governance-aware status, and the loopback workspace;
- no tool accepts a repository escape hatch, raw command, Git arguments, remote, or credential;
- one exact aggregate candidate receives the complete evidence and semantic review required by
  actual reach;
- local landing is a single compare-and-swap update and happens at most once;
- landing history durably attributes supplied intent, recommendation, unit results and actors, decisions,
  governance, evidence, review, and parent;
- remote publication remains off by default and can publish only the exact landed commit to the
  existing upstream;
- failed, rejected, invalidated, stale, or conflicting work remains reachable until explicit
  authorized discard; and
- only the Git-mechanics tests described in §15 remain in the maintained suite.

The implementation should be judged by the handoff it can defend:

> Given only the repository, its Invariant refs, and an exact handoff capsule, can a different
> harness explain what is allowed, resume the permitted work, and return one correct, exact,
> durably attributable result without trusting the previous model's memory?
