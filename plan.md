# Implement the governance gateway

This is the handoff plan for the next implementation agent. The governing design is protocol
version 2 in [`protocol/protocol.md`](protocol/protocol.md); the Python implementation target is
[`docs/SPEC.md`](docs/SPEC.md). Read both before editing code. Where this plan is ambiguous, the
protocol wins.

## Outcome

Replace the version-one task harness with a repository-bound governance gateway that:

- compiles accepted semantics into deterministic obligations;
- recommends whether work stays whole or the actual admissible parallel frontier;
- lets the harness run the workers but requires scoped grants for governed consequences;
- stores active change state, work, decisions, and attribution in Git rather than disposable
  runtime receipts;
- verifies and lands one exact aggregate candidate atomically; and
- resumes from a typed handoff after process, MCP, or model-session loss.

Do not preserve version-one schemas or add a migration path. Replace them directly.

## Repository rules

- Work directly on local `main` and commit completed changes there.
- Never push. Remote publication is the user's decision.
- Update `protocol/protocol.md` before any further protocol behavior change, then update
  `docs/SPEC.md` and code.
- Do not use repository-local `skills/intent-*` as agent instructions.
- Retain or add tests only for Git capability detection, refs and ledgers, linked worktrees,
  exact-tree construction and evidence, atomic landing, concurrency, recovery, and bounded remote
  publication. Do not add tests for prose, prompts, semantic-policy choices, MCP annotations,
  presentation, or private non-Git helpers.
- Preserve unrelated user changes. Use `apply_patch` for file edits.

## Starting point

The current implementation is protocol version 1:

- active tasks and receipts live under `.invariant/runtime`;
- one task corresponds to one worker branch;
- parallel plans are proposed and scheduled by the host, then only validated by core;
- records select context and verifiers but do not have a closed directive compiler;
- the MCP server exposes 19 version-one tools and launches the CLI in a child process; and
- landing already has useful exact-tree, compare-and-swap, concurrency, and bounded-push mechanics.

Reuse the Git primitives and guarantees. Replace the ownership model and durable state around them.

Before the first edit, run:

```bash
git status --short --branch
uv lock --check
uv run --frozen pytest tests/test_git_capabilities.py tests/test_lifecycle_guarantees.py tests/test_remote_push.py
```

Record any pre-existing failure; do not “fix” unrelated work.

## Implementation order

### 1. Establish version-two protocol values

- Replace the enums and typed values in `src/invariant/protocol.py` with protocol version 2:
  change stages, outcomes, directive kinds, capability names, decision states, enforcement posture,
  event kinds, ids, requests, and result projections.
- Add canonical serializers and full-digest validation. Machine results must never abbreviate an oid
  or SHA-256.
- Replace configuration parsing with the version-two keys from SPEC §10.
- Update the repository's own `.invariant/records/**` and `.invariant/config.yml` directly to valid
  version-two forms. Keep the existing record ids and authority anchors where their meaning remains
  correct; add directives that make the constraints operational.
- Reject version-one config, records, receipts, and protocol inputs. Do not add compatibility
  branches.

Stop condition: the package imports, current tracked governance validates under version two, and no
public result can emit `protocol: 1`.

### 2. Build the Git ledger before rebuilding lifecycle

Create `src/invariant/ledger/` with event values, deterministic reduction, the Git store, and
handoff values.

- Write ledger commits with `git hash-object`, `git mktree` or equivalent plumbing, `git
  commit-tree`, and compare-and-swap `git update-ref`.
- Use `refs/invariant/changes/<change-id>` and the exact snapshot/event tree specified in SPEC §4.2.
- Validate the first-parent event chain, payload digests, operation ids, transitions, and referenced
  objects on every load.
- Anchor otherwise unreachable work/candidate commits with refs or additional ledger parents.
- Implement idempotent appends keyed by `operation_id` and request digest.
- Implement token-free `change.handoff` capsules and causal validation. Export/import may follow
  after local handoff works, but the object set and verification interface must be explicit rather
  than transcript-based.

Git-mechanics coverage:

- state survives service restart and deletion of `.invariant/runtime`;
- two concurrent appends preserve both valid events or return one precise causal conflict;
- a corrupt parent, digest, transition, or missing referenced object is rejected; and
- an old handoff capsule cannot roll the ledger backward.

Stop condition: a change can be opened, inspected, handed off, and resumed using only repository
objects and refs.

### 3. Implement semantic selection and the normative compiler

Create `src/invariant/governance/` and move record/locator behavior out of the current broad
`semantics` and `mechanics/governance.py` modules.

- Parse the four version-two record kinds as immutable typed values.
- Resolve canonical Markdown anchors and compute record digests at an exact tree.
- Implement declared selection, actual-diff selection, domain parents, contract edges, and semantic
  `revisit_on` dependencies.
- Implement the seven directive shapes and deterministic composition rules from protocol §4.
- Produce one `ObligationSet` with source attribution for every effect.
- Treat unknown, contradictory, unresolved, or source-less effects as invalid governance.
- Keep `relations`, `facets`, source material, audits, and discoveries open and non-authoritative.

Do not parse prose into permissions. Model-backed reasoning may select scope or propose structured
objects, but only typed fields compile.

Stop condition: lifecycle and gateway code can ask one pure compiler what context, denials,
authority, reviews, verifiers, ordering, parallel limits, containment, and blocks apply.

### 4. Make Invariant own the recommendation

Create `src/invariant/planning/`.

- Define recommendation, unit, claim, dependency, conflict, provider, reliance, frontier, and digest
  values.
- Compose a semantic planning request from the goal and Invariant-selected context. Adapt the
  existing local-provider boundary only to return a typed recommendation proposal.
- Validate unique ids, concrete claims, acyclic dependencies, normalized path-prefix overlap,
  interface overlap, sole contract providers, provider-before-consumer ancestry, governed changes,
  candidate-created checks, and the 32-unit bound.
- Return concrete repair diagnostics for at most two planner retries. Fall back to one conservative
  unit if no valid planner is available.
- Derive the conflict graph and exact largest admissible ready set with a deterministic bounded
  bitset search. Apply tracked and host capacity as ceilings. Persist the recommendation before any
  work grant.
- Recompute the frontier from ledger state whenever a grant, attempt, convergence, or revocation
  changes what is live.

The external harness may request a recommendation and may run fewer units. Remove every API that
lets it inject an arbitrary plan and then call that plan Invariant's recommendation.

Stop condition: the same goal, base, governance, and planner proposal produces the same validated
recommendation digest and frontier; invalid proposals create no work ref.

### 5. Add capability decisions and grants

Create `src/invariant/gateway/`.

- Implement the closed privileged-capability vocabulary and capability-specific rules from SPEC
  §7.2. Ledger-only preparation and narrowing operations remain causally checked but do not require
  a recursive grant.
- Evaluate policy, current ledger, recommendation/frontier, compiled obligations, exact resources,
  and containment in the documented order.
- Persist every state-changing decision, including denial and missing authority.
- Generate 256-bit bearer tokens; store only their SHA-256 digests. Return raw tokens once and redact
  them everywhere else.
- Revalidate all causal bindings at use. Implement single-use consumption, replay-safe results,
  explicit revocation, and stale-grant diagnostics.
- Start with the `uncontained` provider and report `advisory` honestly. Do not claim filesystem,
  ref, credential, or network containment that the implementation cannot prove.

Privileged services must accept a grant token, not a boolean such as `approved`, `reviewed`,
`allow_open`, or `force`.

Stop condition: no privileged application operation is callable without the matching current grant,
and every decision explains its policy/record sources.

### 6. Replace task receipts with the change lifecycle

Rebuild `src/invariant/lifecycle/` around `ChangeService` and the ledger reducer.

- Replace `task` with `change`, `unit`, and `attempt` concepts.
- Derive stage from events. Do not persist a mutable stage as authority.
- Implement action events and exact bindings for recommendation, semantic review, independent
  review, governance acceptance, and user authority.
- Ensure an action response can satisfy only its exact goal, ledger, recommendation, candidate,
  governance, and evidence context.
- Record authorship so an author cannot relabel itself as an independent reviewer.
- Implement resume, grant refresh/revocation, invalidation without deletion, and separate authorized
  discard.
- Remove active truth from `.invariant/runtime/briefs`, `.invariant/runtime/tasks`, plans, leases,
  and receipt files. Runtime becomes cache only.

Do not retain a shadow version-one lifecycle. Remove obsolete task paths once each caller uses the
new service.

Stop condition: deleting runtime during an active multi-unit change loses no durable state or
committed work, and resume returns the same next obligation or an explainable causal update.

### 7. Reuse Git mechanics for isolated units and one aggregate candidate

- Generalize current linked-worktree creation to durable attempt refs at
  `refs/invariant/work/<change>/<unit>/<attempt>`.
- Consume `worktree.create`; associate the worktree with the current `worktree.write` grant.
- Require clean committed submission and compute actual paths/interfaces from Git.
- Reject out-of-claim work without deleting it or converging it.
- Converge units into `refs/invariant/candidates/<change>` in deterministic topological order using
  compare-and-swap.
- For changed contracts, converge the sole provider before creating dependent consumer worktrees;
  use the provider-converged candidate as their exact base.
- Reuse exact-tree verification, but make all evidence point to the aggregate candidate and compiled
  verifier set.

Git-mechanics coverage:

- sibling worktrees are isolated;
- conflicting or overlapping submissions cannot silently converge;
- an out-of-claim diff is retained and rejected;
- provider work is an ancestor of the consumer base;
- candidate CAS preserves a competing valid convergence; and
- evidence for one candidate cannot authorize another.

Stop condition: a one-unit and a genuinely parallel change both produce one exact aggregate
candidate without moving the integration target.

### 8. Put landing and publication behind grants

- Adapt current landing code to consume `integration.land`, recompute actual obligations, and create
  the version-two deterministic attestation.
- Bind change, goal, recommendation, unit result/actor, decision, governance, evidence, review, and
  parent digests.
- Preserve compare-and-swap, dirty-checkout, untracked-collision, conflict, inert-movement, and
  interrupted-bookkeeping behavior.
- Make reconciliation inspect the transaction and attested commit; it must never rerun the change.
- Separate `remote.publish` into its own post-landing grant and event. Retain the exact-source,
  existing-upstream, no-force behavior.
- Update history validation for version-two trailers and out-of-band coverage.

Git-mechanics coverage:

- concurrent landing has exactly one winner;
- stale grants and changed candidates never move the target;
- restart between ref movement and ledger completion reconciles exactly once;
- copied or rewritten attestations fail parent/tree validation; and
- remote rejection leaves the local landed commit intact.

Stop condition: the integration commit alone carries the compact portable provenance required by
protocol §8.6, while the ledger can explain it in full.

### 9. Replace MCP with the real gateway

- Change `src/invariant/mcp_server.py` to construct one repository-bound
  `InvariantApplication` and call it in-process.
- Replace the 19 version-one tools with exactly the version-two tools in SPEC §8.2.
- Remove the generic CLI child-process bridge and all per-call temporary JSON transport files.
- Bind a stable `harness:<instance>` principal at startup and preserve worker actor separately.
- Return protocol denials, stale results, blocks, and actions as successful typed MCP exchanges.
- Return bearer tokens only from `invariant_capability_request`; redact them from all reads.
- Keep stdio as the only transport. Do not add remote MCP until authentication is designed.

Do not add tests for tool names, annotations, or documentation parity. Verify the server manually
with a real stdio MCP client: initialize, list tools, open a change, obtain a recommendation, inspect
the frontier, request a denied publication capability, restart, and resume from handoff.

Stop condition: a harness can perform the entire managed lifecycle without a generic command tool or
repository escape hatch, and MCP restart changes no durable result.

### 10. Rebuild the operator CLI and remove obsolete code

- Make CLI commands thin calls into `InvariantApplication`.
- Implement the human surface in SPEC §9 and retain JSON protocol envelopes.
- Compound human commands may request and immediately consume minimum grants but must show whether
  enforcement is managed or advisory.
- Remove version-one task, plan, lease, receipt, and MCP command paths after their callers are gone.
- Remove dead compatibility wrappers, schemas, guidance, dashboard fields, and host behavior rather
  than leaving both designs active.
- Update README, protocol README/model, CLI basics, and examples to describe only the implemented
  behavior after the implementation actually works.

Stop condition: `rg` finds no version-one protocol marker, obsolete state path, or documentation
claim outside historical Git data.

## Final verification

Run the complete permitted mechanics suite and packaging checks:

```bash
uv lock --check
uv run --frozen pytest tests/test_git_capabilities.py tests/test_lifecycle_guarantees.py tests/test_remote_push.py
uv build
git diff --check
```

Also perform one manual end-to-end scenario in a temporary repository:

1. initialize version-two policy and records;
2. open a change whose semantic recommendation has two independent units and one dependent
   contract consumer;
3. verify that only the first admissible frontier receives write grants;
4. stop the MCP server and remove runtime caches;
5. start a new server, resume from handoff, and verify exact refs and attribution;
6. submit and converge the provider, then create the consumer from that new base;
7. converge the final candidate, capture evidence and review, request landing, and land once;
8. verify the trailers and ledger explanation; and
9. verify that publication is denied while tracked policy is off.

Inspect `git status`, review the full diff, and commit directly to local `main`. Do not push.

## Definition of done

Do not call the implementation complete merely because the MCP tools exist. It is complete only
when all four statements are true:

1. Accepted semantics deterministically cause observable obligations or denials.
2. Invariant records the maximum admissible parallel frontier; the harness only executes within it.
3. A new process can resume active work and attribution from Git-backed state without the previous
   model or transcript.
4. One exact aggregate candidate is verified, atomically landed, and durably attributable to its
   goal, recommendation, workers, decisions, governance, and evidence.
