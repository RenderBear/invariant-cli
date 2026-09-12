# Invariant protocol

**Version 1.** This document defines the implementation-independent contract for Invariant, a
protocol for constructing a governance layer around complex agentic work. One logical Invariant
kernel governs one Git common directory and every harness, agent, and worker that asks to change it.

The governance layer is the composition of two inseparable parts:

1. a **semantic kernel**, which selects accepted intent, identifies questions that still need
   resolution, compiles closed consequences, and decides which scoped capabilities may exist; and
2. a **Git-grounded lifecycle**, which binds those decisions to immutable objects, durable events,
   isolated work, exact-tree evidence, and compare-and-swap integration.

The semantic kernel without the lifecycle is advice. The lifecycle without the semantic kernel is
repository automation with no account of meaning. A conforming Invariant implementation provides
both and keeps their handoff causally explicit.

Invariant does not execute agent work. It turns supplied intent and accepted repository meaning
into decisions about what work may happen, recommends the admissible shape of concurrent work,
issues narrowly scoped capabilities, verifies the exact result, and records what was authorized. A
harness still chooses models, starts workers, schedules permitted work, and carries messages. Git
still stores the exact objects and moves refs.

The boundary is:

```text
intent supplier        harness                 Invariant                         Git
state desired     ->    reason and execute ->  semantic kernel + lifecycle  -> objects and refs
accepted promises      workers and tools       decide, verify, attest           exact causal history
```

The governing rule is:

> Open semantics, closed consequences.

Accepted prose remains expressive. Invariant never pretends to compile arbitrary language into a
complete formal model. It does require every accepted record to have defined protocol effects, and
it permits only a small, versioned vocabulary of mechanical consequences. Those consequences—not a
worker's recollection of the prose—select context, constrain capabilities, order work, require
authority and evidence, and block landing.

The words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, and **MAY** are normative. Words in
**bold** name protocol objects. Fixed-width text is literal.

---

## 1. Execution and authority boundary

### 1.1 Execution is not authority

**Execution** is the ability to cause an operational effect: run a worker, write a worktree, execute
a verifier, move a ref, publish a commit, or remove retained work. **Authority** is the attributable
right to supply or resolve the intent that makes a consequence legitimate. Possessing one never
implies the other.

A harness may have broad execution access while having no authority to decide repository meaning.
An intent supplier may authoritatively state the desired outcome while having no repository or
shell access. A model may execute work without a resolution capability, or receive a narrowly
scoped resolution capability without receiving any additional execution tool.

Invariant evaluates these axes independently:

- an **execution capability** permits one closed operational consequence and is subject to
  containment and causal revalidation; and
- a **resolution capability** permits one actor to answer one bound semantic action within supplied
  intent and accepted policy. It supplies decision authority, not operational access.

No field called `auto`, no model selection, and no ability to call a tool grants authority.

### 1.2 Authority has two inputs

Authority is not a single human-versus-agent mode. It consists of:

1. **intent supply** — an attributable statement of the desired state or accepted promise, supplied
   by a user. Protocol version 1 pins intent supply to `user:` authority; policy-, record-, and
   event-originated suppliers are reserved for a later version and tracked policy MUST reject them
   now; and
2. **resolution capability** — a narrow, revocable entitlement to settle one identified ambiguity
   when supplied intent and accepted governance do not determine the answer.

Intent supply establishes the question and its bounds. It is not a bearer capability and cannot be
manufactured by a model. A resolution capability names the action, actor, accepted intent, exact
causal state, allowed response schema, and whether delegation to a model is permitted. It MAY be
passed to a model as part of a typed action request. The response remains a proposal until the
kernel validates and consumes that exact capability.

A resolution capability cannot widen its intent, change policy, impersonate its supplier, authorize
execution, or answer a different action. Policy changes always require fresh `user:` intent supply.
If no valid capability is available, the action remains `needs-authority`; model confidence is
irrelevant.

### 1.3 Ownership

The three parties have non-overlapping responsibilities.

| Party | Owns | Does not own |
|---|---|---|
| Intent supplier | desired state, accepted promises, and explicit policy decisions | worker execution, implied permission beyond the supplied intent |
| Harness | model choice, worker processes, scheduling within an Invariant recommendation, retries, user interaction | manufacturing intent or resolution authority, governance decisions, integration movement, attestation |
| Invariant | intent binding, record selection, normative compilation, work-shape recommendation, resolution and execution capability decisions, isolation, exact-tree verification, integration and publication gates, durable attribution | implementation, model intelligence, general shell execution |
| Git | immutable object identity, refs, linked worktrees, ancestry, compare-and-swap primitives | meaning, authority, safe parallelization |

A model response is a proposal or an assertion. It is never a capability, verification result, or
accepted repository meaning merely because a model produced it.

A human host MAY retain conversations, provider handles, project registrations, and live-presence
hints outside repository truth. It MAY compose several typed protocol operations into an interactive
command, but every repository consequence still passes through the same capability, exact-candidate,
authority, and landing rules. A one-setting policy command counts as fresh direct user intent only
when it deterministically constructs that exact policy candidate, obtains user acceptance, and lands
it through the governed lifecycle; command convenience is not a policy bypass.

### 1.4 Managed and advisory consequences

A **managed consequence** is an operation for which the worker has no path around Invariant. The
kernel holds the relevant ref, credential, or operating-system permission and performs the operation
only after consuming a valid capability grant.

An **advisory consequence** is one for which the worker retains an out-of-band path. Invariant still
records and checks the rule on its managed path, but MUST NOT describe the rule as enforced against
that worker.

Every capability decision reports `enforcement: managed` or `enforcement: advisory`. A deployment
MUST default to `advisory` unless the containment mechanism is configured and verified. A harness's
claim that it withheld a capability is attribution, not proof of containment.

For example, `remote.publish` is managed only when write workers lack usable remote credentials and
network or Git access sufficient to publish, while the Invariant process alone holds the bounded
publication capability. A repository instruction saying “do not push” does not establish that
condition.

### 1.5 Authority is attributable, not inferred

Every normative decision names an **authority locator**. The standard forms are:

| Locator | Meaning |
|---|---|
| `user:<identity>` | an authenticated or explicitly recorded human decision |
| `policy:<key>` | accepted tracked repository policy |
| `record:<kind>:<id>@<digest>` | one accepted record at one exact version |
| `agent:<provider>/<run>` | a model assertion made under delegated policy |
| `harness:<instance>` | a host assertion, such as worker identity or containment posture |
| `kernel:<repository>/<event>` | a deterministic Invariant decision recorded in the change ledger |
| `design:<locator>` | accepted repository design at the selected integration tree |

Invariant proves what it observed and bound together. It does not prove the real-world identity
behind a host-supplied locator unless the transport authenticates that identity. Responses and
attestations MUST preserve that distinction.

Every durable event records both the asserted actor and the transport principal that supplied the
assertion. A different asserted actor does not create independent authority when the transport
principal is unchanged. Independent review requires both a distinct actor and a distinct transport
principal from every contributing attempt. Direct user authority additionally requires the asserted
`user:` locator to equal the authenticated transport principal.

A `user:` transport principal exists only on a transport the host authenticates. The kernel MUST
refuse to open a ledger transport for a `user:` principal that carries no authentication method,
and every event records the method under which its principal was bound. The reference host treats
an interactive terminal outside any runtime worktree, with no provider run in progress, as
authenticated; it refuses `user:` principals over MCP and from every provider process. This is
containment of the host process and is reported as advisory: an actor holding the host's
operating-system identity can still imitate the host, and the protocol does not pretend otherwise.

Every accepted record has a derived **record authority**: `user:<identity>` when direct user
authority accepted the landing that last introduced or changed the record, and
`agent:<provider>/<run>` when a delegated resolver accepted it. Record files carry no authority
field; the value is read from attested integration history and is `candidate` for a record changed
in an unlanded candidate. Changing or retiring a user-authored record requires `user` resolution
regardless of delegation, so a shape the user described and accepted supersedes agent judgement.
Under delegation an agent may add records and revise agent-authored ones.

Repository policy is user-owned. An agent MAY propose policy but MUST NOT accept a policy change.
The policy from the integration parent governs the candidate that changes it. Creating, changing,
or removing a governance record is instead a bound semantic resolution: the parent policy's
resolution delegation determines whether a user or an independent secondary agent may accept the
exact candidate.

---

## 2. State and durability

One logical Invariant **kernel** is attached to each Git common directory. Every implementation
resolves the Git common directory and primary worktree before reading state. A nested Git repository
has its own kernel; tracked Invariant state nested inside the same repository is invalid.

### 2.1 Tracked governance

The integration history carries portable repository authority:

```text
.invariant/config.yml
.invariant/records/semantic/<id>.yml
.invariant/records/domain/<id>.yml
.invariant/records/contract/<id>.yml
.invariant/records/constraint/<id>.yml
.invariant/SOURCES.yml
.invariant/sources/<material>
.invariant/audits/<id>.yml
.invariant/discoveries/<id>.yml
```

Initialization creates only `config.yml`. Records exist only after acceptance through the governed
landing lifecycle. There is no authoritative generated index; indexes are deterministic views of
the files at an exact tree.

The commit that first introduces `config.yml` is the repository's governance trust root. Every
later first-parent commit that changes tracked policy, records, sources, audits, or discoveries MUST
be an Invariant landing with a valid attestation. `state.validate` evaluates the accepted integration
tree and its first-parent history, never mutable worktree governance; an uncommitted governance
edit is invalid state rather than provisional authority.

### 2.2 Durable operational ledger

Active work MUST NOT depend on a process, conversation, MCP connection, working directory, or
disposable runtime file surviving. Each **change** has a Git-backed ledger rooted at:

```text
refs/invariant/changes/<change-id>
```

The ref points to an append-only chain of ledger commits. Each commit has the preceding ledger event
as its first parent and contains a canonical change snapshot plus the new event. A ledger event binds
at least:

- repository identity, change id, supplied intent, supplier, and intent digest;
- integration target and captured head;
- selected governance and policy digests;
- recommendation id and digest;
- unit, attempt, actor, capability decision, and grant ids;
- work and candidate refs with their exact tips or trees;
- evidence, review, pending action, completion, and invalidation state; and
- the prior ledger event id.

Ledger updates use compare-and-swap. Concurrent writers retry from the winning ledger head or fail
with `concurrent_ledger_movement`; they never discard another event. A change ledger ref has no
wall-clock expiry and is never pruned implicitly. A completed change MAY be archived by moving its
ledger ref to `refs/invariant/archive/<change-id>`; archival moves one ref and deletes nothing, and
the landing attestation remains portable without it. Ordinary operations MAY read the head event's
canonical snapshot instead of replaying the chain; `state.validate` MUST verify the whole chain of
every unarchived ledger.

Generated work remains reachable through dedicated refs:

```text
refs/invariant/work/<change-id>/<unit-id>/<attempt-id>
refs/invariant/candidates/<change-id>
```

A completed landing is portable in ordinary integration history. Active change refs are durable
inside their Git common directory but are not assumed to transfer in an ordinary clone or fetch.
Cross-repository handoff requires an explicit export that includes the ledger, work, candidate, and
referenced Git objects; import verifies repository identity and every object before installing any
ref.

### 2.3 Disposable runtime

The primary worktree may contain self-ignored caches:

```text
.invariant/runtime/worktrees/...
.invariant/runtime/verifications/...
.invariant/runtime/logs/...
.invariant/runtime/locks/...
.invariant/runtime/transport/...
```

Losing this directory may cost worktree checkouts, logs, and reusable computation. It MUST NOT lose
an accepted record, active change, work commit, candidate, decision, grant, pending action, or
completion fact. An implementation reconstructs those from Git refs and objects.

Host-owned session transcripts, provider conversation handles, provider preferences, registered
project paths, and web-observer state are also non-authoritative local data. Losing them MUST NOT
change accepted governance or the durable change ledger.

### 2.4 Standing

| Object | Standing | Durable home |
|---|---|---|
| Policy | repository authority ceiling | integration history |
| Semantic, domain, contract, constraint record | accepted governance | integration history |
| Source, audit, discovery | attributable evidence, never authority by itself | integration history |
| Recommendation | normative execution envelope for one supplied intent and base | change ledger |
| Decision and capability grant | scoped operational authority | change ledger |
| Action response and review | attributable assertion bound to its inputs | change ledger |
| Work, candidate, verification | exact causal fact or observation | Git refs/objects and ledger |
| Landing attestation | completed result and provenance | integration history |
| Runtime file or conversation | cache, transport, or presentation only | local and disposable |

### 2.5 Handoff

`change.handoff` returns a **handoff capsule**, not a prose summary. The capsule identifies the
ledger head, intent digest, base, current stage, recommendation, ready and active units, exact work and
candidate tips, outstanding obligations, live grants, pending actions, and attribution chain.

A receiver resumes by presenting that capsule to `change.resume`. Invariant accepts it only when the
ledger head is current and every referenced object and governance digest resolves. If the integration
target or governance moved, Invariant recomputes consequences before issuing further grants. Time
alone never makes a change stale; causal movement does.

---

## 3. Governance records

Canonical Markdown carries the full argument: proposition, rationale, evidence, alternatives,
consequences, and revision conditions. YAML records give that meaning stable identity, scope,
authority, invalidation, and closed mechanical effects.

Every record has a SHA-256 **record digest** over its normalized envelope and the exact canonical
Markdown sections it names. Selection and landing always identify records by id and digest.

### 3.1 Locators

| Locator | Refers to |
|---|---|
| `architecture:<path>#<anchor>` | a Markdown heading with an explicit stable anchor |
| `repo:<path>` | a tracked path or prefix |
| `interface:<name>` | a named interaction surface |
| `domain:<id>` | a domain record |
| `contract:<id>` | a contract record |
| `semantic:<id>` | a semantic record |
| `constraint:<id>` | a constraint record |
| `capability:<name>` | one capability in the closed protocol vocabulary |
| `audit:<id>` | a saved audit |
| `command:<path>` | an executable verifier from the candidate tree |
| `test:<path>` | a test resolved and run from the candidate tree |
| `runner:<name>` | a configured verifier runner |

Every locator MUST resolve in the tree against which it is evaluated. A missing anchor, target,
record, verifier, or dependency is invalid governance and blocks capability issuance and landing.

### 3.2 Semantic records

```yaml
version: 1
id: processor-source-ownership
document: architecture:docs/architecture.md#processor-source-ownership
status: active
applies_to: [repo:services/document-processor, interface:processor-source]
revisit_on: [repo:.gitmodules, semantic:processor-external-ownership]
verifies: [command:checks/ordinary-processor-source.sh]
directives:
  - id: source-ownership-review
    kind: require-review
    mode: independent
supersedes: [processor-external-ownership]
relations:
  challenges: [semantic:processor-external-ownership]
facets:
  confidence: accepted
```

`id`, `document`, `status`, `applies_to`, `revisit_on`, `verifies`, `directives`, and `supersedes`
have protocol meaning. Authority is derived from history (§1.5), never declared. `relations` and `facets` remain open vocabularies and acquire no
mechanical effect implicitly.

When a change's declared or observed reach intersects `applies_to`, the record MUST be selected. A
record's own file selects it only when the exact file is reached; a declared prefix over the records
directory is an estimate of where writing may happen, not a reach into every record. When a record
is reached, every record that names it in `revisit_on` is selected with it. Its
canonical prose enters context, its verifier and directive obligations compile, and the exact
candidate receives at least attributable semantic review. A directive may strengthen that review to
independent; it cannot remove it. A semantic record therefore always changes behavior even when it
contains no explicit directive: it changes retrieval, review, invalidation, and attestation.

`revisit_on: semantic:<id>` is a dependency edge. Changing the premise's envelope or canonical prose
reopens dependents. Open relations never propagate invalidation.

A record is retired only by an accepted candidate that names it and meets its compiled review and
authority obligations. The retired envelope remains in integration history, and revision preserves
the relationship by supersession; there is no in-place erasure of accepted meaning.

### 3.3 Domains

```yaml
version: 1
id: ocr.orchestrator
responsibility: Selects OCR engines and distributes work.
parent: ocr
scope: [repo:src/ocr/orchestrator]
interfaces: [interface:OcrEngine]
architecture: [architecture:docs/architecture.md#ocr-orchestration]
contracts: [ocr.engine-protocol.v1]
```

A **domain** is a stable responsibility, retrieval boundary, and planning primitive. It is not
automatically a directory or ownership lock. Its scope and interfaces help the recommender keep
cohesive responsibility together, detect cross-domain work, and select contracts. Splitting one
strongly cohesive domain requires an explicit recommendation rationale; sharing a domain does not
alone forbid parallelism.

### 3.4 Contracts

```yaml
version: 1
id: ocr.engine-protocol.v1
assertion: Every engine accepts OcrRequest and returns OcrResult.
between: [ocr.orchestrator, ocr.engine.external]
surfaces: [interface:OcrEngine, repo:schemas/ocr-engine.json]
architecture: [architecture:docs/architecture.md#ocr-engine-protocol]
verifies: [command:scripts/verify-ocr-engine-protocol]
```

A **contract** is an accepted, observable promise relied on across domains. Its verifiers are
mandatory whenever a candidate reaches the contract or its surfaces. A plan that creates or changes
a contract has exactly one provider unit. Every affected consumer depends on the provider and starts
from the provider-converged candidate. Unchanged consumers of an unchanged contract MAY run in
parallel.

Changing a contract assertion, surface, architecture, verifier, or provider implementation also
requires independent candidate review unless a `user:` authority accepts the exact candidate.

These ordering and verification effects are intrinsic to the contract type; they do not depend on a
model remembering the assertion.

### 3.5 Constraints

```yaml
version: 1
id: bounded-remote-publication
assertion: Repository work is not published by agents.
applies_to: [capability:remote.publish]
material: [repo:.invariant/config.yml, repo:src/invariant/mechanics/landing.py]
surfaces: [repo:src/invariant/mechanics/landing.py]
verifies: [test:tests/test_remote_push.py]
directives:
  - id: no-agent-publication
    kind: deny-capability
    capability: remote.publish
```

A **constraint** is an accepted restriction. It MUST contain at least one verifier or directive, so
it always has an observable protocol consequence. Its assertion explains the rule; the closed field
defines what Invariant does.

### 3.6 Evidence and establishment

Sources, audits, and discoveries can motivate governance but cannot create it. Establishment keeps
observation, proposal, authority, and acceptance distinct. An agent MAY draft records and
directives. Adding, changing, or removing records is a semantic resolution governed by the
integration parent's `authority.resolution.delegation`. When delegation is `secondary-agent`, a
fresh agent actor and transport principal, distinct from every candidate author, MAY accept the
candidate by consuming an action-bound `intent.resolve` capability. When delegation is `user`, the
candidate remains pending for direct user authority. Policy changes always require a `user:`
authority and cannot be delegated. A candidate that touches any tracked governance path (§2.1)
requires that resolution; an audit or source change is not exempt because it names no record.

Review and resolution are distinct obligations. A required review is satisfied only by a review
response, and a required resolution only by a resolution response of the kind the kernel opened.
An accepted review MUST NOT count as acceptance of a governance candidate, and an acceptance MUST
NOT stand in for a required review. A candidate that needs both is not ready to land until it
holds both.

Before acceptance, Invariant MUST make the exact candidate, new or changed directives, their
compiled consequences, and the authority that would govern inspectable. A human decision surface
SHOULD lead with a concise plain-language account of what would become accepted, its material
effects, and any cautions; raw records, provenance, locators, and object identities remain available
on demand rather than replacing that account. A secondary-agent resolution request receives the
same exact material in typed form. Acceptance is bound to that candidate tree. A later edit requires
new acceptance.

### 3.7 Validation

Tracked state is validated on every dependent read and before every decision or landing. Unknown
closed fields, unknown directive kinds, malformed YAML, unresolved locators, duplicate ids, cycles,
contradictory directives, stale digests, and unattested governed history are invalid state.

Open prose, `relations`, and `facets` are preserved but never interpreted as hidden permission.

---

## 4. Normative compilation

### 4.1 Fixed consequences

Invariant compiles policy and selected records into an **obligation set**. The only protocol effects
are:

1. context selection, which is a consequence only when delivered: the harness MUST present the
   selected records' canonical prose, verifiers, and review obligations to every worker attempt and
   every reviewer it runs for the change;
2. capability denial;
3. required authority;
4. required review;
5. required verifier;
6. serialization or a maximum parallel width;
7. provider-before-consumer ordering;
8. causal invalidation; and
9. prevention of candidate acceptance, landing, publication, or destructive cleanup.

No adapter or implementation may add behavior to an open prose field. New mechanical effects
require a protocol version or a namespaced extension that is explicitly enabled by tracked policy.

### 4.2 Directive vocabulary

Each directive has a stable `id` unique within its record and exactly one shape:

| `kind` | Required fields | Consequence |
|---|---|---|
| `deny-capability` | `capability` | the capability cannot be granted in the selected scope |
| `require-resolution` | `capability`, `resolver` | the capability requires a matching resolution or fresh supplied intent |
| `require-review` | `mode` | candidate review must be `attributable` or `independent` |
| `require-verifier` | `locator` | the exact candidate must carry passing evidence |
| `serialize` | `on` | units reaching any named locator cannot run concurrently |
| `limit-parallelism` | `maximum` | caps simultaneous write grants for the selected scope |
| `require-containment` | `capability`, `enforcement` | refuses the capability unless the reported posture is met |

`resolver` is `user`, `secondary-agent`, or `any-attributable`; `enforcement` is `managed`;
`maximum` is a positive integer. A `secondary-agent` resolver is represented by an attributable
`agent:` actor holding the action-bound capability. Unknown values are invalid, not ignored.

### 4.3 Precedence and composition

The compiler is deterministic:

- tracked policy is the authority ceiling and cannot be widened by a record;
- all applicable restrictions accumulate;
- denial wins over a policy default or satisfied requirement;
- the strongest resolver, review, and containment requirement wins;
- required verifiers form a set union;
- serialization edges form a set union;
- parallel limits take the minimum; and
- incompatible requirements make governance invalid rather than choosing silently.

The result identifies every source as `policy:<key>` or `record:<kind>:<id>@<digest>`. A decision is
invalid if its explanation cannot be reconstructed from those sources.

### 4.4 Selection and actual reach

Compilation first uses the declared intent, paths, interfaces, domains, contracts, and requested
capability. A capability request always selects active constraints and semantic records that apply
to `capability:<name>`, even when no source path changes. That produces a pre-work envelope. Before
convergence and again before landing, Invariant computes the **actual reach** from the exact Git diff
and selected records. Newly reached governance adds obligations and may suspend, replan, or revoke
further grants. Declared scope can never hide observed scope.

---

## 5. Capability gateway

### 5.1 Closed capability vocabulary

Capabilities have one of two classes. The distinction is normative and every decision and grant
records it.

The single standard **resolution capability** is:

| Capability | Permits |
|---|---|
| `intent.resolve` | answer one exact typed semantic action within supplied intent and delegated policy |

`intent.resolve` may govern recommendation, semantic review, independent review, or governance
acceptance responses. Its resource is the action id. It is never a generic permission to decide.

The standard **execution capabilities** are the closed operational consequences that can execute
code, create writable state, converge work, move refs, publish, invalidate, or destroy retained
work:

| Capability | Permits |
|---|---|
| `worktree.create` | create one isolated unit attempt from its authorized base |
| `worktree.write` | implement inside that attempt's claims |
| `verification.run` | run only selected verifier identities against an exact tree |
| `candidate.converge` | add one completed unit result to the aggregate candidate |
| `integration.land` | compare-and-swap one verified candidate onto its target |
| `remote.publish` | publish the exact landed commit to an already configured upstream |
| `change.invalidate` | abandon a change without erasing attributable history |
| `work.discard` | delete retained unlanded work after explicit authority |

There is no generic shell, arbitrary Git, arbitrary filesystem, credential, network, or “admin”
capability.

Read-only inspection, opening a durable ledger from attributable supplied intent, recording a work
submission, and requesting or revoking a grant do not themselves require a recursive grant.
Recording a semantic recommendation or review is an action response and consumes `intent.resolve`
unless the response is direct intent supply from an allowed supplier. These operations remain
schema-validated and causally bound.

There is no direct policy-edit operation. A policy edit is ordinary isolated work whose exact
candidate is evaluated under the integration parent's policy, receives direct user acceptance, and
lands through `integration.land`.

### 5.2 Decisions

A **capability request** names the actor, change, unit and attempt when applicable, capability,
resource, exact causal base, declared claims, requested operation, and transport identity.

Invariant returns one **decision**:

| Decision | Meaning |
|---|---|
| `granted` | obligations are satisfied and an opaque grant was issued |
| `denied` | accepted governance prohibits the operation |
| `needs-authority` | a named authority action could make a new decision possible |
| `stale` | causal inputs moved; recomputation is required |

A decision contains the compiled sources, obligations, enforcement posture, reason, and digest.
Denial and missing authority are durable events, not transport failures.

### 5.3 Grants

A **grant** is an opaque bearer handle to one narrow consequence. It records its class as
`resolution` or `execution` and binds:

- decision digest, actor, capability, repository, change, unit, and attempt;
- integration target and exact base;
- path, interface, domain, contract, and governance claims;
- selected policy and record digests;
- required evidence and review obligations;
- enforcement posture;
- use count or `single_use`; and
- causal invalidators.

The grant event is appended to the change ledger before the handle is returned. An execution handle
conveys no semantic authority. A resolution handle conveys no execution access. An actor label
without the required handle is insufficient, and a handle presented for another resource is
refused.

Grants are causally scoped rather than trusted because they are recent. Before use, Invariant
revalidates the target, branch or candidate tip, governance digests, plan state, prior uses, and
conflicting live grants. Time alone does not validate or invalidate a grant. A stale grant is never
silently broadened; the caller requests a new decision.

### 5.4 Consequence mediation

Privileged operations—intent resolution or governance acceptance, candidate convergence,
integration landing, remote publication, invalidation, and discard—MUST consume a matching grant inside
the kernel unless the authority operation is direct allowed intent supply. Worktree
write grants are audited against the resulting diff. A worker that changes paths beyond its claims
does not gain authority over them: the work is retained, the unit is rejected with
`parallel_claim_violation`, and affected grants are revoked.

---

## 6. Work recommendation and parallel bounds

### 6.1 One change, zero or more parallel units

A **change** is one requested outcome and one eventual atomic integration result. A **unit** is a
schedulable part of that change. A small or tightly coupled change remains one unit. Invariant MUST
NOT recommend parallelism merely because multiple workers are available.

A change opens with a **reach estimate**: the paths and, when known, the interfaces, domains, and
contracts the intent is expected to touch. The estimate is the blast radius the harness commits to
before any worker runs. It MUST be non-empty, and the repository root is not an estimate:
`repo:.` is rejected with `unbounded_scope`. Actual reach is still measured from the diff (§4.4).

Before write workers are dispatched, `change.recommend` evaluates the exact base, supplied intent, selected
governance, domains, contracts, paths, interfaces, configured capacity, and any retained discoveries.
The semantic planner receives the **planning context**: the selected records with their closed
fields and canonical prose, every domain scope and interface, every contract's surfaces and parties,
the compiled obligations including serialization and parallel limits, the tracked tree beneath the
estimated reach, and the single question the planner answers: whether the intent splits into
mutually exclusive, contractually independent units. It returns a **work recommendation** with:

```yaml
version: 1
id: <recommendation-id>
change: <change-id>
base: <commit>
intent_digest: <sha256>
disposition: parallel        # or single
units:
  - id: api
    objective: Evolve the OCR request contract and provider.
    claims: [repo:schemas/ocr-engine.json, repo:src/ocr/provider, contract:ocr.engine-protocol.v1]
    provides: [contract:ocr.engine-protocol.v1]
    relies_on: []
    depends_on: []
    checks: [command:scripts/verify-ocr-engine-protocol]
  - id: ui
    objective: Adopt the evolved OCR request contract in the client.
    claims: [repo:src/ui/ocr, contract:ocr.engine-protocol.v1]
    provides: []
    relies_on: [contract:ocr.engine-protocol.v1]
    depends_on: [api]
conflicts: []
maximum_parallelism: 1
recommended_frontier: [api]
governance: [record:contract:ocr.engine-protocol.v1@<digest>]
```

The recommendation has a digest and is appended to the change ledger. A semantic planner MAY help
construct it, but the planner receives only Invariant-selected context, returns typed output, and
has no authority to validate or issue grants. A harness MAY supply the planner's proposal itself
when it is the model; the proposal is still validated as a proposal. Invariant owns normalization,
validation, conflict derivation, and the final recommendation. An invalid proposal is recorded as
`recommendation.rejected` with its diagnostic and the proposal it rejected before the conservative
result is recorded. Without a valid semantic recommendation, the conservative result is one unit
over the reach estimate.

### 6.2 Valid units

Parallel units are valid only when at least two can make meaningful progress independently and each
has:

- one concrete objective;
- non-empty path, interface, domain, or contract claims;
- declared dependencies and contract relationships;
- an independently attributable worker result; and
- a convergence path into one aggregate candidate.

Invariant derives conflicts from overlapping claims, selected `serialize` directives, contract
provider rules, exclusive governance changes, and configured capacity. Overlap without an ordering
edge is invalid. A shared repository root or domain does not by itself create a conflict; a shared
claimed path, interface, changing contract, or serialized locator does.

### 6.3 The admissible frontier

At any ledger state, the **admissible frontier** is the set of dependency-ready units that do not
conflict with each other or with live write grants. A unit whose attempt has been submitted is
complete for frontier purposes: it is not ready, it is not live, and it holds no slot while it waits
to converge. `maximum_parallelism` is the greatest permitted
number of simultaneous write grants after policy limits. `recommended_frontier` is the preferred
subset to dispatch now.

This is the protocol's sole statement of safe parallelism for that change and base. A harness MAY
run fewer units or serialize the frontier. It MUST request a revised recommendation before widening
it, changing claims, skipping a dependency, or starting a conflicting unit. The harness owns when
and where permitted workers run; Invariant owns which units may be live together.

### 6.4 Reconciliation with reality

Recommendations are grounded, not omniscient. Invariant compares each submitted unit's actual diff
and interfaces with its claims. Hidden overlap, new governance reach, a changed contract, or target
movement invalidates the affected frontier. Invariant then narrows, reorders, or replaces the
recommendation before issuing more write grants. Completed work remains reachable.

When a unit changes a contract, it is the sole provider. The provider converges first. Dependent
unit worktrees are created from that converged candidate tip, never from the obsolete original base.
After all units converge, the whole candidate follows one review, verification, and landing path.

---

## 7. Change lifecycle

### 7.1 Shape

```text
open change
  -> durable ledger + supplied-intent/base/governance snapshot
  -> recommend one unit or a bounded work graph
  -> issue grants for the admissible frontier
  -> harness dispatches and runs workers in isolated attempts
  -> submit exact unit results; check actual claims; converge causally
  -> construct one exact aggregate candidate
  -> compile actual obligations + capture exact-tree evidence
  -> obtain attributable semantic or authority actions when required
  -> issue and consume integration.land
  -> atomic local landing
  -> optionally issue and consume remote.publish
  -> append completion; retain ledger and attestation
```

### 7.2 Stages

| Stage | Meaning |
|---|---|
| `opened` | supplied intent, supplier, base, and initial governance are durable |
| `recommending` | work shape requires semantic or authority input |
| `ready` | a recommendation exists and at least one unit may receive a grant |
| `executing` | one or more unit attempts are live or awaiting submission |
| `converging` | completed unit results are being assembled causally |
| `evidencing` | the exact aggregate candidate and required observations are being produced |
| `awaiting-action` | a blocking review or authority action is pending |
| `ready-to-land` | every obligation is satisfied for the current exact candidate |
| `cleanup-required` | a privileged effect succeeded but ledger bookkeeping was interrupted |
| `completed` | local landing is attested; publication status is recorded separately |
| `invalidated` | further work is stopped; history and retained work remain inspectable |

The stage is a projection of the ledger, not mutable truth in a runtime file.

### 7.3 Actions

Semantic judgment and missing authority use one typed **action** transport. Each action binds an id,
kind, schema, supplied-intent digest and supplier, ledger head, selected governance, and—when a
candidate exists—its exact tree and evidence ids.

Actions may request a work recommendation, scoped intent resolution, semantic review, independent
review, governance acceptance, or new user intent. A response for a different intent, ledger head, recommendation, or
candidate is stale.

At any ledger state the kernel exposes the ordered **resolution list** for a change: pending reviews
first, then governance acceptance, then supplied intent, then other bound resolutions. Each item
names its kind, its resolver, the bindings a response must repeat, and the plain-language brief the
kernel can derive from the candidate. When policy delegates resolution, the harness presents that
exact list to a distinct agent run item by item. When policy assigns resolution to the user, the
host presents the same list to the user, who responds per item. Both paths produce the same typed
responses and the same ledger events. A delegated response consumes the action's `intent.resolve` grant. Direct user
intent supply is recorded as a new attributable intent statement and supersedes the pending bounds
where policy permits. Editing a ledger, runtime file, or worktree is not a response.

An adapter owns only its private reasoning. It cannot issue grants, mark verification passed, change
stages, converge work, move refs, or manufacture authority. Rejection preserves the candidate and
records defects. A corrected tree receives new evidence and a new review; an author cannot mark its
own work independent.

### 7.4 Resume, revoke, invalidate, and discard

Every lifecycle operation is idempotent against an unchanged ledger head and exact inputs. Resume
reconstructs state from refs, cleans only provably disposable cache, and continues from the first
unsatisfied obligation.

Revocation prevents future use of a grant and records why. Invalidation stops a change without
deleting its work. Discard is separate, destructive, and requires its own capability and explicit
authority. No timeout or missing worker heartbeat implicitly discards work.

---

## 8. Verification and landing {#verification-and-landing}

### 8.1 Candidate identity

The final **candidate** is a Git tree, not a worktree directory. Invariant constructs it from the
captured integration head and causally converged unit commits without moving the integration ref.
The candidate record binds the base, tree, unit result trees, recommendation digest, actual reach,
and governance digests.

A dirty unit worktree cannot be submitted. A conflict leaves all refs and work intact and produces
`merge_conflict`. A candidate change invalidates candidate-bound evidence, review, and landing
grants.

### 8.2 Verification

For the exact candidate, Invariant MUST:

1. recompute actual reach;
2. reselect policy and governance from the integration parent;
3. compile the complete obligation set;
4. validate unit claims and causal provider order;
5. run every required contract, record, policy, and supplied verifier;
6. bind evidence to candidate tree, base, verifier identity, environment, and mechanics version;
7. obtain every required attributable or independent review;
8. obtain every required resolution from its configured resolver; and
9. refuse a landing grant until all structural, behavioral, semantic, authority, and containment
   obligations pass.

A review cannot override a failed verifier. A passing verifier does not prove prose beyond the
observable property it tests.

### 8.3 Routine changes

A candidate is **routine** only when actual reach selects no record requiring semantic review, no
governed material changes, no contract changes, all required mechanical checks pass, and integration
history is attested. Routine means no human or model action is required. It never bypasses
isolation, exact-tree construction, capability decisions, verification, or atomic landing.

### 8.4 Landing {#landing}

`integration.land` is a single-use capability performed only on the gateway's managed path. Its
decision still reports `advisory` unless containment proves that the worker cannot move the target
out of band. On consumption Invariant:

1. confirms the grant, candidate, recommendation, obligations, and evidence still match;
2. confirms the integration target equals the grant's expected head;
3. confirms the integration worktree can be synchronized without overwriting tracked or untracked
   user work;
4. creates the attested commit; and
5. moves the target by compare-and-swap or not at all.

Any failed check, conflict, stale decision, claim violation, missing authority, changed candidate, or
concurrent non-inert target movement leaves the integration ref unchanged.

If the target advances, landing authority becomes stale. Invariant retains the candidate and
requires recomputation and fresh evidence against the new parent; it never silently rebases a
reviewed tree. `integration.recompute` is that explicit recomputation: it consumes a
`candidate.converge` grant for the resource `recompute:<new-parent>`, merges the retained candidate
onto the current target head with the captured base as merge base, and records a new candidate
whose base is the new parent. A conflict leaves everything unchanged and returns `merge_conflict`.
The new candidate has no evidence, review, or resolution; every candidate-bound grant is stale, and
the change returns to `evidencing`.

### 8.5 Publication {#publication}

Remote publication is a distinct capability after local landing. It is denied by default. When
enabled and granted, Invariant may push only the exact landed commit to the integration branch's
already configured upstream. It never creates or selects a remote or upstream. A rejection cannot
undo the local landing and is recorded as publication failure.

### 8.6 Landing attestation

The landing commit is the portable result. It carries:

| Trailer | Value |
|---|---|
| `Invariant-Protocol` | literal protocol version `1` |
| `Invariant-Change` | change id |
| `Invariant-Intent` | intent digest, supplier, and supplying transport principal |
| `Invariant-Plan` | recommendation id and digest |
| `Invariant-Unit` | repeated unit id, result tree, attributed actor, and transport principal |
| `Invariant-Decision` | each privileged decision digest consumed by landing |
| `Invariant-Authority` | accepted governance or supplied-intent action id, event digest, asserted authority, and transport principal |
| `Invariant-Governance` | each selected record id and digest |
| `Invariant-Evidence` | exact candidate evidence-set digest |
| `Invariant-Review` | review digest, mode, authority, and transport principal when required |
| `Invariant-Landing-Parent` | expected integration parent commit |

Trailer serialization is deterministic. Validation recomputes the first-parent candidate and
rejects missing, malformed, copied, or stale bindings. History validation applies the same
acceptance rule as the landing gate: a landing that changes tracked governance is valid only when
its ledger, or its portable trailers, carries an accepted governance resolution by a resolver the
parent policy allows. A review alone never attests a governance change. A claimed actor is durable provenance of
what the gateway received; it is authenticated identity only when the named transport supplied
authentication.

### 8.7 Out-of-band history

Humans and tools may move the integration branch outside Invariant. The protocol does not pretend
otherwise. Any movement from a change's captured base makes its candidate and landing authority
stale. Copied trailers never make a cherry-pick an Invariant landing; a backport requiring
attestation is a new change against the backport target.

---

## 9. Wire contract

### 9.1 Envelope

Every operation returns one typed envelope:

```json
{
  "protocol": 1,
  "command": "change.recommend",
  "status": "ok",
  "outcome": "ready",
  "result": {},
  "diagnostics": []
}
```

`status` is `ok`, `blocked`, or `error`. `blocked` is reserved for a valid mechanical or
verification stop; it is not a transport failure. `outcome` is:

| Outcome | Meaning |
|---|---|
| `completed` | the requested operation completed |
| `ready` | the next permitted work is described in `result` |
| `needs_input` | one or more typed actions are pending |
| `denied` | governance prohibits the requested capability |
| `stale` | causal movement requires recomputation |
| `blocked` | a valid mechanical or verification condition prevents progress |
| `failed` | invocation, state, transport, or internal failure prevented a valid result |

Denial, staleness, missing authority, and verification failure are valid protocol results. MCP or
process transport MUST NOT translate them into transport errors.

Closed-vocabulary decoding is part of the operation boundary. An unknown capability or locator
returns this envelope with its stable diagnostic code; it MUST NOT escape as a transport exception.

### 9.2 Operation families

The protocol exposes typed operations in these families:

```text
state.*          validate and inspect repository governance
context.*        retrieve selected records, compiled obligations, and the planning context
change.*         open, recommend, inspect, handoff, resume, invalidate, archive
action.*         inspect and respond to typed semantic or authority actions
capability.*     request, inspect, revoke, and consume grants
work.*           create attempts, inspect, submit, and retain unit results
candidate.*      converge, inspect, evidence, review
integration.*    land, recompute, and reconcile
publication.*    inspect and publish the exact landed result
```

Consumers use fields, ids, schemas, and digests. They never parse human prose to discover a granted
capability and never edit runtime or refs directly.

### 9.3 Output discipline

- Read-only operations never mutate refs, worktrees, tracked state, ledgers, or caches.
- State-changing operations name the expected ledger and ref heads.
- Successful retries with unchanged causal inputs return the same result or the recorded successor.
- Standard output contains only the selected response format.
- Successful verifier logs may remain in disposable runtime; their digests and identities are
  durable.
- Unknown fields in closed protocol objects are rejected.

### 9.4 Exit status

| Exit | Outcomes |
|---|---|
| `0` | `completed`, `ready`, `needs_input`, `denied`, or `stale` |
| `1` | `blocked` |
| `2` | `failed` |

### 9.5 Stable diagnostic codes

At minimum, conforming implementations use these codes:

| Area | Codes |
|---|---|
| Repository | `not_repository`, `not_initialized`, `nested_invariant`, `unsupported_git`, `invalid_state`, `invalid_policy` |
| Governance | `unknown_record`, `unresolved_locator`, `invalid_directive`, `contradictory_directives`, `stale_governance`, `authority_required`, `unauthenticated_principal` |
| Ledger | `missing_change`, `corrupt_ledger`, `concurrent_ledger_movement`, `stale_handoff`, `missing_object` |
| Recommendation | `invalid_recommendation`, `unbounded_unit`, `unbounded_scope`, `overlapping_claims`, `contract_order_violation`, `parallel_limit_exceeded`, `recommendation_required` |
| Capability | `unknown_capability`, `capability_denied`, `capability_required`, `stale_grant`, `grant_consumed`, `grant_revoked`, `containment_required` |
| Work | `missing_worktree`, `dirty_worktree`, `parallel_claim_violation`, `work_retained`, `merge_conflict` |
| Verification | `verification_failed`, `missing_evidence`, `stale_evidence`, `semantic_review_required`, `independent_review_required`, `stale_review` |
| Landing | `concurrent_ref_movement`, `dirty_integration_checkout`, `untracked_collision`, `landing_sync_conflict`, `invalid_attestation` |
| Publication | `remote_publication_denied`, `remote_upstream_missing`, `remote_upstream_invalid`, `remote_push_failed` |
| Invocation | `invalid_invocation`, `invalid_protocol_output`, `internal_error` |

Messages are for humans and may change. Codes and typed details are stable within protocol version 1.

---

## 10. Guarantees and limits

A conforming managed deployment guarantees:

1. **Normative semantics.** Every selected record changes context, obligations, review,
   verification, ordering, invalidation, or capability decisions. Open prose never silently grants
   authority.
2. **Bounded parallelism.** Invariant, not the harness, records the admissible concurrent frontier.
   Conflicting work does not receive simultaneous managed write grants.
3. **Harness independence.** The harness controls real workers and execution strategy but cannot
   widen a managed recommendation or perform a privileged managed consequence without a grant.
4. **Durable continuity.** Process exit, model-session loss, MCP restart, or elapsed time does not
   erase active work or its attribution. Causal movement is re-evaluated on resume.
5. **Exactness.** Plans, grants, work, evidence, reviews, and landing bind to Git object ids and
   governance digests.
6. **Isolation.** Each concurrent attempt has its own work ref and linked worktree.
7. **Atomicity.** The integration ref moves by compare-and-swap or remains unchanged.
8. **Attribution.** The landed result traces to its supplied intent, recommendation, units, actors, decisions,
   governance, evidence, review, and parent.
9. **Retention.** Failed, rejected, revoked, invalidated, or conflicting work remains inspectable
   until an explicitly authorized discard.
10. **Bounded publication.** Local landing and remote publication are separate; publication is off
    by default and can target only the exact landed commit and existing upstream.
11. **Authority provenance.** Record authority is derived from attested landing history, `user:`
    principals exist only on host-authenticated transports, and a review never substitutes for a
    required resolution.

Invariant does not guarantee that accepted prose is wise, that a semantic reviewer reasons
correctly, that declared actor identity is authenticated without an authenticating transport, or
that advisory rules stop out-of-band tools. It guarantees that its own decisions and managed
consequences are derived, scoped, checked, and durably attributable as specified here.
