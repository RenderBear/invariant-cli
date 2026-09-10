# Durable semantic reasoning

Treat typed fields as coordinates for prose, not as a substitute for interpretation. Outcomes,
acceptance IDs, domains, paths, and boundary dispositions identify what must be revisited; the
meaning still lives in the user's language, accepted architecture, contracts, discoveries, and the
behavior of the repository.

## Keep three accounts separate

Reason explicitly about three things that may disagree:

1. **Requested meaning** — the behavior and constraints the user is asking for now.
2. **Accepted meaning** — responsibilities, decisions, and relied-on promises already authoritative
   in the repository.
3. **Observed behavior** — what code, tests, schemas, configuration, history, and operations
   currently appear to do.

Observed behavior is evidence, not automatic authority. Documentation is not automatically true
because it is prose, and implementation is not automatically normative because it runs. When the
three accounts disagree, name the contradiction instead of silently choosing the most convenient
one. Decide whether it is an implementation defect, stale documentation, an unresolved discovery,
or a deliberate change that needs authority.

## Look for durable meaning

Ask the counterfactual question: could a future change be locally reasonable but systemically wrong
unless it knew this fact? Durable meaning commonly appears as:

- stable responsibility and ownership boundaries;
- the authoritative copy of state and the permitted direction of synchronization;
- interfaces, schemas, events, files, configuration, or storage relied on by another component;
- identity, ordering, idempotency, deduplication, consistency, and transaction guarantees;
- persistence across restart, browser closure, retries, failover, or migration;
- failure containment, retry ownership, compensation, recovery, and observability expectations;
- compatibility windows, rollout order, deprecation rules, and irreversible transitions;
- deliberate restrictions on future implementation, even when many implementations would work.

Do not reduce these questions to nouns such as “PostgreSQL,” “React,” or “queue.” Preserve the
operational meaning: which state is authoritative, what survives, who may write it, what another
domain relies on, and under which failure or transition conditions.

## Trace responsibility and reliance

For each important behavior, ask:

- Who initiates it, who owns its policy, and who merely transports or renders it?
- Which component can make the final decision, and which components must accept that decision?
- Where is state created, mutated, persisted, reconstructed, expired, or reconciled?
- Which consumers would break if the shape, timing, ordering, or failure semantics changed?
- Is the dependency incidental today, or is another part of the system entitled to rely on it?

A domain is justified by a stable responsibility, not by a folder. A contract is justified by
reliance across responsibilities, not by every function call. Architecture prose is justified when
rationale, ownership, permitted shape, or a consequential tradeoff must survive beyond this task.

## Reason across time and failure

Do not inspect only the successful steady state. Follow behavior through creation, partial progress,
retry, cancellation, restart, concurrent execution, stale clients, version skew, migration, and
cleanup. Ask what happens before a write commits, after one side succeeds, when a process disappears,
and when old and new code coexist.

Temporal behavior often carries the real promise. “Jobs are shown” is weaker than “non-terminal
jobs are reconstructed exactly once after reopening while session-only events are not restored.”
Preserve that distinction in prose even if the current schema stores only stable IDs around it.

## Preserve uncertainty without becoming vague

When evidence is incomplete, retain a structured argument in prose:

- the observation;
- the evidence and searched scope;
- the leading interpretation;
- plausible alternatives;
- the consequence of choosing incorrectly;
- whether existing authority resolves the choice;
- the smallest next inspection or user decision that would resolve it.

Use confidence to control further investigation, not to manufacture authority. A meaningful absence
requires a bounded search: say what locations, names, concepts, history, and generated artifacts were
checked, and bind that claim to an exact tree.

## Resolve only within authority

Compose compatible evidence and reversible implementation choices without ceremony. Stop at a
semantic fork when proceeding would weaken an accepted promise, choose between incompatible user
outcomes, invent ownership, or turn uncertainty into a durable rule. If a decision is needed, ask
one behavior-level question: state the observation or inference, the accepted rule if one exists,
the practical consequence, and the recommended option. Do not ask the user to interpret internal
IDs or approve a mechanical command.

Agent authority permits judgment inside the current request and accepted repository authority. It
does not create authority over security, money, production data, external effects, irreversible
transitions, or contradictory user goals.

## Resist ontology pressure

Not every useful fact deserves a domain, contract, ADR, or permanent record. Do not create governance
to make the system look complete. A discovery may resolve into code, a test, documentation,
follow-up work, another discovery, or no artifact. Conversely, do not hide a durable promise as an
implementation detail merely because no record exists yet.

Prefer the smallest coherent place that future work will actually retrieve. Amend an existing owner
when possible. Record new governance only when the meaning is authoritative, durable, and likely to
guide or constrain future work.

## Close the reasoning pass

State the requested behavior in plain language, the relevant accepted meaning, the strongest
evidence, any contradiction or uncertainty, and the durable-boundary conclusion. Keep IDs and
locators attached to that explanation rather than allowing them to replace it.
