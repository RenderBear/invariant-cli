# Invariant protocol

**Version 1.** This document defines the contract an Invariant implementation keeps with a Git
repository, with the records that repository carries, and with the hosts and agents that change it.
It is independent of any command-line surface. The reference implementation is the `invariant`
CLI; its own design of record describes commands, configuration, and mechanics and is subordinate
to this document.

The protocol has five parts:

1. **Tracked state** — what lives in the repository and what standing each object has.
2. **Records** — the envelopes that bind accepted meaning to canonical prose.
3. **The task lifecycle** — the one path by which a repository is changed, its stages, its two
   suspension points, and the typed actions that resolve them.
4. **Verification and landing** — how a candidate is identified, checked, and applied atomically,
   and what the landed commit carries.
5. **The wire format** — the JSON envelope, outcomes, exit statuses, and diagnostic codes.

Words in **bold** name protocol objects. `Fixed-width` text is literal.

---

## 1. Tracked state

One logical Invariant **kernel** is attached to each Git common directory. Every implementation
resolves the Git top level first and uses only `<worktree-root>/.invariant`. Tracked nested
Invariant state inside one Git repository is invalid; a genuine nested repository or submodule has
its own kernel, verification boundary, and landing lifecycle. Linked worktrees share one runtime
through the primary worktree.

### 1.1 Repository history

```text
.invariant/config.yml          repository policy
.invariant/records/semantic/<id>.yml semantic records (§2.1)
.invariant/records/domain/<id>.yml   domain projections (§2.2)
.invariant/records/contract/<id>.yml contract projections (§2.3)
.invariant/records/constraint/<id>.yml constraint projections (§2.4)
.invariant/SOURCES.yml         grounding-source origins and scopes (§2.5)
.invariant/sources/<material>  repository-held source material
.invariant/audits/<id>.yml     saved audits: evidence, not rules
.invariant/discoveries/<id>.yml
```

Initialization creates `config.yml` only. Record directories exist only once accepted records
exist; there is no tracked aggregate index. Implementations derive indexes deterministically from
the record files and never manufacture empty semantic authority.

### 1.2 Runtime

Generated state is shared by linked worktrees and self-ignored at its root. It is outside history
but never outside the Invariant namespace:

```text
.invariant/runtime/briefs/<task-id>.yml
.invariant/runtime/tasks/<task-id>/...                     active receipt and private state
.invariant/runtime/history/tasks/<task-id>/<landed-commit>/ completed argument archive
.invariant/runtime/verifications/<evidence-id>.*
.invariant/runtime/plans/<id>.yml
.invariant/runtime/leases/<unit>.yml
.invariant/runtime/history-validation/<target>.yml
.invariant/runtime/worktrees/<task-id>-<nonce>/...
```

Loss of the runtime loses active tasks and nothing else: no accepted record, no landed commit, and
no archived history depends on it.

### 1.3 Standing

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
| Verification result | reproducible observation for one exact tree | ignored cache until explicit cleanup |

Only accepted governance binds future work. Evidence can motivate governance but cannot become
authority without explicit adoption through the lifecycle in §3.

### 1.4 Locators

Every cross-reference in tracked state is a typed locator:

| Locator | Refers to |
|---|---|
| `architecture:<path>#<anchor>` | one anchored Markdown section; the canonical prose |
| `repo:<path>` | a tracked path or path prefix |
| `interface:<name>` | a named interface surface |
| `domain:<id>` | a domain projection |
| `contract:<id>` | a contract projection |
| `semantic:<id>` | a semantic record |
| `audit:<id>` | a saved audit |
| `command:<path>` | an executable verifier in the candidate tree |
| `test:<path>` | a test file resolved and run from the candidate tree |
| `runner:<name>` | a configured named runner |

An implementation validates that every locator resolves in the tree it is evaluated against. An
`architecture:` locator carried by accepted governance resolves only to a Markdown heading with an
explicit `{#anchor}` suffix. Human-facing lookup may recognize heading slugs, but mutable heading
text is never a durable record identity. A record whose explicit `architecture:` anchor no longer
exists in its document is invalid state, and invalid state blocks every landing until it is
repaired.

---

## 2. Records

Ordinary Markdown is the source of truth. The YAML record files are a thin, deterministic envelope
for retrieval, authority, and verification. An implementation never parses canonical prose into a
closed claim taxonomy.

### 2.1 Semantic records — `records/semantic/<id>.yml`

```yaml
version: 1
id: processor-source-ownership
document: architecture:docs/architecture.md#processor-source-ownership
authority: user:task:import-processor#turn-3
status: active
applies_to: [repo:services/document-processor, interface:processor-source]
revisit_on: [repo:.gitmodules, semantic:processor-external-ownership]
verifies: [command:checks/ordinary-processor-source.sh]
supersedes: [processor-external-ownership]
relations:
  challenges: [semantic:processor-external-ownership]
facets:
  confidence: accepted
```

Fixed fields and their meaning:

| Field | Meaning |
|---|---|
| `id` | stable identity, unique within the registry |
| `document` | the exact canonical prose section the record interprets |
| `authority` | why the interpretation may govern; an attributable reference |
| `status` | `active` or `superseded`; revision is preserved, never overwritten |
| `applies_to` | locators by which the record is retrieved from path, interface, or domain context |
| `revisit_on` | locators whose change reopens review of this record |
| `verifies` | executable witnesses that project part of the meaning |
| `supersedes` | ids this record replaces |
| `relations`, `facets` | open vocabularies; never given mechanical behavior implicitly |

The filename is `<id>.yml` and must equal the enclosed `id`. One file contains exactly one record.

`revisit_on: semantic:<id>` is an explicit dependency edge. Retrieval follows those edges so a
dependent record is present whenever its premise is. Invalidation propagates only when the
premise's envelope or canonical prose changes, not when ordinary code covered by the premise
changes.

Every record has a **digest**: SHA-256 over the normalized envelope and the exact canonical
Markdown section in the tree being evaluated. Retrieval returns the digest with the record.
Landing binds the digest into the commit (§4.4).

### 2.2 Domains — `records/domain/<id>.yml`

```yaml
version: 1
id: ocr.orchestrator
responsibility: Selects OCR engines and distributes work.
authority: user:task:ocr-architecture#turn-4
parent: ocr
architecture: [architecture:docs/architecture.md#ocr-orchestration]
contracts: [ocr.engine-protocol.v1]
```

A domain is a stable responsibility and a retrieval index, not a directory or an ownership lock.
Validation covers identifiers, parent references, cycles, contract references, and architecture
anchors. Unknown fields are rejected. The filename is `<id>.yml` and one file contains exactly one
domain projection.

### 2.3 Contracts — `records/contract/<id>.yml`

```yaml
version: 1
id: ocr.engine-protocol.v1
assertion: Every engine accepts OcrRequest and returns OcrResult.
authority: user:task:ocr-architecture#turn-4
between: [ocr.orchestrator, ocr.engine.external]
surfaces: [interface:OcrEngine, repo:schemas/ocr-engine.json]
architecture: [architecture:docs/architecture.md#ocr-engine-protocol]
verifies: [command:scripts/verify-ocr-engine-protocol]
```

A contract requires identifiable reliance (`between`), referenced architecture, and at least one
executable verifier. A verifier passing is evidence for the contract, not proof of every
interpretation. A promise with no stable observable consequence is recorded as architecture or a
constraint, not as a contract. The filename is `<id>.yml` and one file contains exactly one
contract projection.

### 2.4 Constraints — `records/constraint/<id>.yml`

A constraint is an accepted repository restriction with an attributable authority, at least one
domain in `applies_to`, defining `material`, and optional surfaces and executable verifiers. It
uses the same direct `<id>.yml` identity rule as every other record projection.

### 2.5 Sources — `SOURCES.yml`

A grounding source is attributable evidence attached to an existing scope: exactly one origin
(`url` or `path` beneath `.invariant/sources/`) and exactly one scope (`domain:<id>`,
`contract:<id>`, or repository-wide). Its id is derived deterministically from its canonical
origin. Source content is presented to agents as untrusted evidence; it can never create or modify
records, and never authorizes work.

### 2.6 Validation

Tracked state is validated on every read that depends on it and before every landing. Malformed
YAML, unknown fields, unresolved locators, dangling anchors, cycles, and unattested integration
history (§4.5) are each reported with a stable diagnostic and the offending location. A task cannot
begin or land against invalid state.

Inspectable locators in an audit's proposed records are validated against the inspected tree before
the audit is persisted. Invalid paths, anchors, authorities, surfaces, material, or verifiers remain
rejected agent output; they never become a resumable adoption proposal.

---

## 3. The task lifecycle

Every repository mutation is a **task**. A task has a caller-chosen, repository-local **id**: it
begins with an alphanumeric character and may contain alphanumerics, `.`, `_`, and `-`. The id
connects the goal, receipt, generated branch, verification, and landing.

### 3.1 Shape

```text
begin
  -> receipt + isolated work branch in a linked worktree
  -> task.created actions                    (suspension point 1)
  -> implementation by the host
  -> exact prospective tree
  -> reach + exact-tree mechanical evidence
  -> candidate.evidenced actions             (suspension point 2)
  -> final verification
  -> atomic local landing
  -> optional configured upstream push
  -> active-state cleanup + completed argument archive
```

**Begin** captures the integration target and its head, records the semantic envelope, creates or
reuses a generated branch in a dedicated linked worktree, and returns the work location. It never
moves the integration checkout, so many tasks may begin concurrently in one clone.

**Finish** constructs the exact candidate, captures evidence, resolves what it can, and either
lands or returns typed actions. It is resumable: running it again after any interruption continues
from the persisted stage.

### 3.2 Stages

| Stage | Meaning |
|---|---|
| `briefing` | an intent-brief adapter is producing the brief |
| `briefed` | the brief is accepted; implementation may begin |
| `awaiting-branch` | assisted execution is waiting for approval to create the branch |
| `implementing` | the host is working in the isolated worktree |
| `implementing-unborn` | as above, on a repository whose integration branch has no commits yet |
| `awaiting-review` | a blocking `candidate.evidenced` action is pending |
| `awaiting-landing` | assisted execution is waiting for approval to move the ref |
| `cleanup-required` | the ref moved but bookkeeping did not complete; reconcile |
| `completed` | landed and archived |

A task that has completed is no longer active. Its archive answers status and evidence queries.

### 3.3 Suspension points and actions

There are exactly two blocking semantic suspension points. Mechanical steps are never hooks, so an
adapter cannot replace branch isolation, evidence collection, verification, or landing.

| Phase | Ordering guarantee | Context |
|---|---|---|
| `task.created` | receipt, target, base, branch, and work location selected; implementation not begun | task, original goal, goal digest |
| `candidate.evidenced` | one exact candidate tree constructed and its mechanical evidence captured; integration has not moved | task, goal digest, candidate tree, evidence ids |

Each persisted **action** has:

```json
{
  "id": "core:candidate-review",
  "adapter": "core",
  "phase": "candidate.evidenced",
  "kind": "review_semantics",
  "blocking": true,
  "schema_id": "invariant://schemas/actions/review-semantics/v1"
}
```

Normal lifecycle output carries only this reference. Expanding an action returns its `prompt`,
`input_schema`, and `context`; the candidate-review context contains the task, goal digest,
candidate tree, reach, changed paths, affected semantics, inferred governance, checks to run,
evidence ids, retained discoveries, any independent-review requirement, and a `review_id`.

Rules:

1. Replaying a phase with unchanged context returns an equivalent pending action or recognizes the
   already accepted response.
2. A response is checked against every available causal binding: the goal digest at intake; goal,
   brief, and candidate-tree digests at final review. A response bound to a different tree is
   stale and refused.
3. Implementation cannot proceed while a blocking `task.created` action remains. Resolving the last
   one advances to implementation without a second begin.
4. The integration ref cannot move while a blocking `candidate.evidenced` action remains.
   Resolving the last one continues to landing automatically, except for an independent assisted
   pause.
5. Changing the candidate while review is pending invalidates the old response; the next finish
   constructs new evidence and a new action.
6. An adapter owns only its private state and action semantics. It cannot choose stages, move
   refs, mark mechanical evidence passed, or authorize repository-wide meaning.
7. Core semantic review uses the same action transport as adapters. There is one response path.
8. A review separates blocking `candidate_defects` from non-blocking `retained_discoveries`.
   `review_mode` is `self-attested` unless the host actually routed the action to an independent
   reviewer; the implementation records provenance and never invents it.
9. A candidate with `gated` reach, or with `open` reach to a contract, requires either attributable
   human acceptance or `review_mode: independent`. An independent reviewer did not author any
   candidate work item and receives the exact candidate in a fresh review session. Self-attestation
   is refused for this boundary. Review cannot override a failed verifier.
10. A rejected or uncertain review does not resolve its action. Its summary and candidate defects
    remain attached to the exact candidate and are returned to the host. A host MAY route those
    defects to a candidate author for correction, but the author cannot convert that rejection into
    acceptance: every corrected tree receives new evidence and, when independence is required, a
    fresh independent review.

Responses are submitted by action id. Editing runtime files is not a response.

### 3.4 The candidate review response

```yaml
version: 1
review_id: <from the action context>
candidate_tree: <exact tree id from the action context>
verdict: accepted            # or rejected
summary: <attributable one-line judgment>
semantic_effect: no-record   # or audit:<id> or recorded
authority: user:task:<id>#review
review_mode: self-attested   # or independent
candidate_defects: []
retained_discoveries: []
```

`semantic_effect` is the **boundary disposition** of the change:

| Disposition | Assertion |
|---|---|
| `no-record` | accepted meaning and durable operational properties are unchanged |
| `audit:<id>` | a fresh scoped audit concludes that no adoption is currently required |
| `recorded` | the change is owned by the supplied accepted governance references |

These are semantic assertions with mechanical validation. A reach classification never manufactures
one. An acknowledgement is an attributable assertion, not proof of comprehension: the implementation
binds it to an exact tree and preserves who asserted what, and cannot tell careful reasoning from a
rubber stamp.

The review has a digest: SHA-256 over the normalized version, review id, candidate tree, verdict,
summary, semantic effect, authority, review mode, candidate defects, and retained discoveries.

### 3.5 When a change is routine

A candidate whose changed paths, interfaces, and domains touch no accepted record, whose
integration range is fully attested, and whose tracked state validates is **routine**. Finish
continues through verification and landing without returning any action. The assessment that
would otherwise be authored is inferred. Any of the following removes a change from the routine
path and produces a `candidate.evidenced` action or a blocking diagnostic:

- a changed path is covered by a record's `applies_to`;
- the candidate touches a record's canonical prose or record file;
- the integration range contains commits not landed through the lifecycle that touched governed
  prose (§4.5);
- tracked state is invalid;
- a supplied check fails.

### 3.6 The assessment

The low-level input to verification is a versioned assessment. Hosts do not author it on the normal
path; finish prepares it.

```yaml
version: 1
goal_digest: <hash>
paths: [src/ocr/engine.py]
interfaces: [OcrEngine]
domains: [ocr.engine.external]
boundary:
  disposition: no-record
governance: []
architecture_reviews: [architecture:docs/architecture.md#ocr-engine-isolation]
checks: [test:tests/test_ocr_engine.py]
```

An assessment is never accepted governance. Whenever the candidate affects accepted meaning,
landing requires an accepted candidate review for that exact tree; an assessment supplied without
one is refused as `semantic_review_required`.

### 3.7 Recovery

Two operations exist only for recovery. **Reconcile** repairs a task whose landing outran its
bookkeeping: it replays an interrupted integration-checkout sync after the ref moved, and archives a
task whose unit trailer already reached the integration branch. **Invalidate** abandons a task and
removes its generated worktree and branch; it refuses to drop uncommitted or unlanded work unless
discarding is explicit.

A failed finish preserves the receipt and worktree so the same id can be inspected and resumed.

---

## 4. Verification and landing

### 4.1 Candidate identity

A **candidate** is identified by exact Git object identity, never by a branch name at a later time:

- `commit:<sha>`;
- `branch:<ref>`, resolved and captured at invocation;
- `staged`, from an explicitly identified worktree and index;
- `merge:<base>:<tip>`, constructed without moving either ref.

The prospective tree is constructed by merging the task branch onto the captured integration head
without moving either ref. If that merge conflicts, the task is refused with `merge_conflict` and
the integration branch is unchanged.

### 4.2 Verification

1. construct and capture the candidate commit and tree;
2. compute actual changed paths and section reach;
3. validate tracked Invariant state;
4. select and run affected semantic and contract verifiers and supplied checks;
5. record command identity, working directory, environment fingerprint, timestamps, duration,
   status, exit code, output digest, and retained log for each;
6. present those observations with the exact candidate to semantic review;
7. validate the resulting authority, architecture acknowledgements, governance references, and
   boundary disposition;
8. rerun volatile checks; reuse only exact-tree evidence whose declared cache policy permits it.

Standalone verification never updates a ref.

**Reach** classifies how far a candidate's effect extends: `local`, `bounded`, `open`, or `gated`.

**Evidence** is addressed by stable id: `candidate:<sha256>` for the constructed candidate and
`state:<sha256>` for a tracked-state validation, plus verifier-specific ids. Evidence is reusable
only for the exact tree, base, verification mechanics version, runner configuration, working
directory, environment, and verifier identity that produced it. Changing the candidate always
invalidates it.

### 4.3 Landing

Landing consumes verification only when the evidence exactly matches the candidate tree, mechanics
version, verifier identities, and governance versions. It then:

1. confirms the integration target still equals the captured head;
2. resolves an already-configured upstream before mutation when publication is enabled;
3. confirms the integration worktree can be synchronized safely;
4. applies the local ref update atomically, as a compare-and-swap against the captured head;
5. may write a disposable successful-history checkpoint; checkpoint failure cannot fail a landing;
6. releases explicitly associated leases only after success;
7. pushes the exact landed commit to the upstream when enabled; a rejected push leaves the verified
   local landing intact and reports it.

Any conflict, failed check, changed candidate, missing review, stale assessment, or concurrent
target advance leaves the target unchanged.

If the target moved under a routine candidate, the implementation rebuilds the candidate on the new
head and re-verifies without restarting semantics. If the target moved under a reviewed candidate
and the movement expands semantic scope, changes governing material, or conflicts, the task returns
to the earlier stage and the old review is invalid.

A dirty integration worktree (tracked changes present) is not synchronized; landing is refused and
the changes are left alone. A finish invoked from inside a task worktree instead of the integration
checkout is refused as `wrong_worktree`.

### 4.4 The landed commit

The landing commit is the durable, greppable record of the change. It carries trailers:

| Trailer | Value |
|---|---|
| `Invariant-Unit: <task-id>` | the task, one per landing |
| `Invariant-Scope: <area>` | the mechanical scope the candidate reached |
| `Invariant-Domain: <id>` | each affected domain |
| `Invariant-Plan: <id>` | the coordination plan, when one applied |
| `Invariant-Boundary: <disposition>` | `no-record`, `audit:<id>`, or `recorded` |
| `Invariant-Landing-Parent: <commit>` | the original first parent, or `unborn` for a root landing |
| `Invariant-Covers: <old>..<new>` | an integration range the landing attests (§4.5) |
| `Invariant-Governance: <locator>` | each accepted governance reference the change is owned by |
| `Invariant-Semantic: <id>@<sha256>` | for each `semantic:` reference, the record digest in the landed tree |
| `Invariant-Architecture: <locator>` | each architecture section acknowledged by review |
| `Invariant-Review-Authority: <locator>` | the human or agent authority that accepted the exact candidate |
| `Invariant-Review-Mode: <mode>` | `self-attested` or `independent` |
| `Invariant-Review-Digest: <sha256>` | digest of the accepted candidate review |

Every attested landing binds its original first parent with `Invariant-Landing-Parent`; validation
therefore detects copied or rewritten landing commits. The three review trailers appear together
whenever a candidate review was required. Landing-history
validation rejects incomplete review provenance and missing, malformed, or stale
`Invariant-Semantic` bindings.

### 4.5 Attestation of the integration range

Commits reach the integration branch without the lifecycle: humans commit directly, branches are
merged by hand, history is rewritten. The protocol does not forbid this. It requires that every
such range be **covered** by the next landing.

Finish computes the range between the last attested commit and the current head. If the range is
non-empty, the next landing carries `Invariant-Covers: <old>..<new>`. If nothing in that range
touched governed prose or registries, coverage is automatic and the change stays routine. If it did,
the affected sections are added to the next candidate's review, whatever that candidate changed.
Until then, validation reports the unattested range as invalid state.

A cherry-pick does not preserve lifecycle identity: copied `Invariant-*` trailers describe the
original first-parent candidate and MUST be removed before the commit is introduced out of band.
The next ordinary landing then covers the cherry-picked commit. A backport that must retain an
Invariant attestation is performed as a new task against the backport branch and receives a new
exact-tree review and landing commit.

An implementation MAY retain a disposable history-validation checkpoint after a successful
landing. It may reuse that checkpoint only when its target, validated head, mechanics version, and
first-parent ancestry still match; otherwise it performs the complete history validation. A
read-only operation never creates or updates the checkpoint, and absence or loss of the checkpoint
changes performance only.

---

## 5. Coordination

Coordination is optional and activated only by a host for work that is genuinely parallel,
independently owned, or handoff-sensitive. Nothing in the lifecycle depends on it; it may depend on
context mechanics, never the reverse.

A host that offers an end-to-end Change operation MUST apply a parallelization policy before it
dispatches write workers. The policy keeps a small or tightly coupled Change in one work item. It
creates multiple work items only when at least two have concrete, non-overlapping claims and can make
meaningful progress independently. Ready work items SHOULD run concurrently; dependency edges, claim
overlap, or a shared mutable surface require ordering rather than optimistic concurrent writes.
The host validates a proposed plan before dispatch. It MAY return concrete validation failures to the
planner for a bounded number of repair attempts; no invalid attempt creates a lease or write worker.

Contract synchronization is causal. `provides` and `relies_on` contain only exact `contract:<id>`
locators; code symbols, schemas, tests, and paths remain interface, verification, or path claims.
Work items that only consume an unchanged accepted contract may
run concurrently. When a work item creates or evolves a contract, it is the sole provider for that
contract in the plan, and every affected consumer depends on it. The host MUST converge the provider
into the Change candidate before dispatching those consumers, and consumers MUST start from that
converged snapshot. This permits independent frontend and backend work without allowing either side
to implement against an obsolete contract. The whole converged candidate is still reviewed,
verified, and landed atomically through one task lifecycle.

A **plan** describes units, dependencies, path/interface/governance claims, provides/relies
relationships, and checks. A **lease** records temporary ownership of a unit against an integration
ground and causal branch tip, with a duration. The implementation validates target and ground
existence, acyclic dependency order, provider-before-consumer edges, unordered claim overlap,
selected governance digests, and lease freshness and liveness. Concurrent acquisition of one lease
grants exactly one holder.

The core implementation never decides to create workers or hold conversations. A public host may do
so under the policy above. Landing does not consult leases except to authenticate coordinated claims
and release the ones explicitly associated with the landed task.

---

## 6. Receipts and the archive

A **receipt** is disposable lifecycle state and an integrity cache. It is created at begin and is
never consumed as landing evidence. It may bind repository identity, the mechanics digest, the
integration target and captured head, the exact goal digest, selected paths, interfaces, and
domains, selected governance digests, and the current boundary disposition. A changed goal, brief,
adapter, or candidate tree invalidates the corresponding cached response.

On successful landing the receipt, evidence, brief, reviews, and a `summary.yml` are archived under
`runtime/history/tasks/<task>/<landed-commit>/`. The summary records initial and final boundary
dispositions, audit and finding coverage, the landing commit, the candidate tree, and structural,
behavioral, and semantic assurance separately. Nothing prunes the archive implicitly.

---

## 7. Wire format

### 7.1 Envelope

Every response is one JSON object:

```json
{
  "protocol": 1,
  "command": "task.finish",
  "status": "ok",
  "outcome": "needs_input",
  "result": { },
  "diagnostics": [ { "code": "stable_code", "message": "human sentence" } ]
}
```

| Field | Values |
|---|---|
| `protocol` | the literal `1` |
| `command` | dotted command name: `task.begin`, `task.finish`, `task.respond`, `task.action`, `task.evidence`, `task.status`, `context.semantics`, `state.validate`, … |
| `status` | `ok` or `error` |
| `outcome` | see §7.2 |
| `result` | command-specific typed data; a lifecycle result carries `task` and, when constructed, `candidate` |
| `diagnostics` | zero or more `{code, message}`; on error the first names the cause |

The lifecycle `result.task` carries `id`, `stage`, `boundary`, `actions` (references only, §3.3),
`assurance` with `structural`, `behavioral`, and `semantic` statuses, and `completion.commit`.
`result.candidate` carries `tree` and `evidence_ids`.

Consumers use fields, action ids, and schemas. They never parse human prose or read runtime files.

### 7.2 Outcomes

| Outcome | Meaning |
|---|---|
| `completed` | the requested operation finished |
| `ready` | state is ready for the host's next step, for example implementation after begin |
| `needs_input` | a blocking action is pending; resolve it by id |
| `awaiting_approval` | assisted execution is paused before a state-changing transition |
| `blocked` | a valid negative result: failed check, conflict, invalid state, semantic review required |
| `failed` | invocation, state, or internal failure prevented a valid result |

### 7.3 Exit status

| Exit | Meaning |
|---|---|
| `0` | completed, ready, needs_input, or awaiting_approval |
| `1` | blocked |
| `2` | failed |

Exit status crosses host boundaries unchanged. An unexpected internal failure still produces the
envelope, with `internal_error` and exit `2`.

### 7.4 Output discipline

- Standard output contains only the selected result format.
- Successful lifecycle output is a state delta; full status, actions, and evidence are fetched by
  dedicated read operations.
- Successful verifier output is retained in ignored logs and summarized; failure responses include
  the relevant output and log path.
- Read-only operations never mutate Git, tracked state, runtime, or receipts.
- State-changing operations identify every intended mutation before applying it and support a
  dry run wherever the result can be computed without mutation.
- Repeating an idempotent operation with unchanged inputs yields an equivalent result.

### 7.5 Diagnostic codes

Codes are stable identifiers. Messages are for humans and may change.

**Invocation and repository**

| Code | Meaning |
|---|---|
| `invalid_invocation` | arguments or input document violate the schema; the message names the field |
| `not_repository`, `not_a_repository` | no Git repository at the resolved root |
| `not_initialized` | no `.invariant/config.yml` |
| `nested_invariant` | tracked Invariant state inside a nested directory of one repository |
| `unsupported_git` | the Git installation lacks a required capability |
| `git_failed` | a Git operation failed; the message carries its output |
| `config_exists`, `invalid_config_key`, `invalid_config_value` | configuration errors |
| `initialization_not_committed` | bootstrap files are uncommitted and must be committed first |
| `missing_file` | a referenced input file does not exist |
| `invalid_yaml` | a tracked or input document is not valid YAML; the message carries the position |
| `internal_error` | unexpected failure; exit 2 |

**Tracked state**

| Code | Meaning |
|---|---|
| `invalid_state` | tracked state fails validation; the message names each violation |
| `unknown_domain` | a domain reference does not resolve |
| `invalid_trailer` | a landing-history trailer is missing, malformed, or stale |
| `source_conflict`, `missing_source_scope`, `dirty_source_index` | grounding-source errors |

**Task lifecycle**

| Code | Meaning |
|---|---|
| `missing_task` | no active task with that id; a completed task answers only status and evidence |
| `task_worktree_exists`, `missing_task_worktree` | generated worktree present when it must not be, or absent when it must exist |
| `wrong_worktree` | a lifecycle operation was invoked from a task worktree instead of the integration checkout |
| `missing_integration_target` | no integration branch is configured and HEAD is detached |
| `empty_change` | the candidate contains no changes |
| `dirty_worktree` | the task worktree has uncommitted changes; the implementation must be committed before finish |
| `untracked_collision` | landing would overwrite an untracked file in the integration worktree |
| `stale_receipt`, `corrupt_receipt` | the receipt no longer matches the repository, or cannot be read |
| `lifecycle_paused`, `change_paused` | assisted execution is waiting for approval |
| `change_needs_input`, `establish_needs_input`, `hook_input_required` | a blocking action is pending |
| `no_pending_action`, `unknown_action`, `ambiguous_action` | action addressing errors |
| `action_limit_reached` | the allowed decision rounds are spent and repository records still need a decision |
| `work_retained` | invalidate refused to drop uncommitted or unlanded work |
| `unrecoverable_task` | the task has no lifecycle state to resume, or awaits cleanup with no landing carrying its unit trailer |
| `operation_blocked` | the operation is refused in the current state; includes a concurrent finish of the same task |
| `operation_failed` | the operation could not complete; the message states why |

**Verification, review, and landing**

| Code | Meaning |
|---|---|
| `verification_failed` | a check failed; the target is unchanged |
| `merge_conflict` | the prospective merge conflicts; the integration branch is unchanged |
| `concurrent_ref_movement` | the target moved after capture and the movement invalidated the candidate |
| `landing_sync_conflict` | the integration worktree was edited after an interrupted landing sync; reconcile |
| `semantic_review_required` | the candidate affects accepted meaning and no accepted review exists for this tree |
| `missing_review`, `candidate_not_accepted` | review absent or rejected |
| `stale_candidate_review`, `stale_adapter_review`, `stale_intent_review`, `stale_intent_brief` | a response is bound to a different goal, brief, or tree |
| `stale_evidence`, `diverged_evidence`, `missing_evidence` | evidence does not match the candidate |
| `stale_governance` | selected governance changed since the receipt was taken |
| `invalid_assessment`, `invalid_boundary`, `invalid_review_discovery` | malformed semantic inputs |
| `authority_required` | the configured authority does not permit the agent to decide this |
| `intent_questions_unanswered`, `intent_not_accepted` | intent-brief adapter responses incomplete or rejected |

**Governance and audits**

| Code | Meaning |
|---|---|
| `invalid_audit`, `no_findings` | audit input errors |
| `invalid_adoption`, `invalid_adoption_projection`, `incomplete_adoption_coverage` | adoption manifest errors |

**Coordination**

| Code | Meaning |
|---|---|
| `invalid_plan`, `missing_plan` | plan errors |
| `parallel_claim_violation` | a parallel work item changed a path outside its declared claim; work is retained |
| `stale_lease` | a landing since the lease's ground touched the leased unit; re-lease against the new ground or release |

**Harness and publication**

| Code | Meaning |
|---|---|
| `missing_agent`, `agent_not_connected`, `agent_login_failed` | no usable provider |
| `agent_timeout` | the provider did not finish within the configured time |
| `invalid_agent_output`, `invalid_protocol_output`, `invalid_invariant_output`, `unsupported_output_schema` | the provider's structured result is unusable |
| `missing_session_id`, `invalid_session_mode`, `missing_adapter` | console session errors |
| `invalid_harness_preference`, `invalid_default_harness`, `default_harness_overridden` | provider preference errors |
| `remote_upstream_missing`, `remote_upstream_invalid`, `remote_push_failed` | publication errors; a local landing is never undone by them |

---

## 8. Guarantees

An implementation of this protocol guarantees, for every task:

1. **Isolation.** Implementation happens in a worktree the integration checkout never sees until
   landing.
2. **Exactness.** Every review, every piece of evidence, and every landing is bound to an exact
   tree id. A response for another tree is refused.
3. **Atomicity.** The integration ref moves by compare-and-swap or not at all. Interruption at any
   point leaves either the old head or the new one, never a partial state, and the same finish
   resumes to completion.
4. **Single landing.** A task lands at most once. A second concurrent finish of the same task is
   refused.
5. **No blind merge.** A conflicting candidate is refused with the target unchanged and the work
   preserved.
6. **Attested history.** Every commit on the integration branch is either a landing or inside a
   range a later landing covers; validation reports the gap until then.
7. **Bounded authority.** Nothing an adapter or provider returns becomes accepted meaning without
   passing through a candidate review bound to an exact tree and carrying an attributable
   authority.
8. **Inspectability.** Every state named here is readable by a typed operation without reading
   runtime files, and every refusal carries a stable code.
