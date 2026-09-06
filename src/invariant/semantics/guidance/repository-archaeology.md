# Repository archaeology

Repository archaeology reconstructs the system's working model from incomplete and sometimes
contradictory evidence. Its purpose is not to inventory every directory. Start from the requested
behavior and progressively discover only enough context to understand responsibility, reliance,
state, failure, and durable constraints.

## Establish the ground

First identify the repository shape that changes how evidence should be interpreted:

- languages, package manifests, build entrypoints, generated-code boundaries, and deployment units;
- executable entrypoints, framework registration, dependency injection, jobs, workers, and hooks;
- test organization, fixtures, schemas, migrations, configuration, and operational scripts;
- architecture documents, ADRs, READMEs, examples, issue references, and comments that explain why;
- recent history around the intended paths, including renames, reversions, and unfinished migrations.

Use names as clues, not conclusions. Search both exact symbols and behavioral concepts. A feature
called “restore jobs” may appear under hydration, reconciliation, recovery, resume, polling,
subscriptions, local storage, or bootstrap code.

## Use a narrow inspection loop

Prefer a widening loop over reading the repository front to back:

1. List tracked files and inspect top-level manifests, repository instructions, ownership files,
   architecture or ADR indexes, schemas and migrations, test entrypoints, CI, and deployment
   configuration.
2. Locate the requested symbols and several behavioral aliases with repository-wide search.
3. Read the smallest complete implementation path, then follow its direct callers, consumers,
   adapters, tests, and persistence boundaries.
4. Compare any named durable domain or interface with its architecture section and executable
   verifier.
5. Inspect focused history only where current evidence cannot explain a consequential choice.
6. Write down contradictions, bounded absences, and unresolved alternatives before expanding the
   search again.

Typical probes include `rg --files`, `rg` over symbols and concepts, package and build manifests,
`git log -- <path>`, focused `git blame`, and `git show` of commits that introduced or reversed the
relevant behavior. Treat generated, vendored, ignored, submodule, and external-service boundaries
explicitly: either inspect their source of truth or state that they were outside the search.

## Trace behavior end to end

Begin at the user-visible or externally observable event and follow it through the repository:

1. entrypoint or trigger;
2. orchestration and policy decisions;
3. interface and serialization boundaries;
4. state reads and writes;
5. asynchronous work, retries, and callbacks;
6. rendering or external response;
7. tests, cleanup, and recovery paths.

Trace both callers and consumers. Imports reveal availability but not necessarily ownership. Look for
who constructs an object, who mutates it, who persists it, who retries it, and who interprets its
failure. Follow data by identity and lifecycle, not only by type name.

## Triangulate evidence

No single source has universal precedence. Compare:

- runtime code for current executable behavior;
- tests for asserted behavior and forgotten edge cases;
- schemas and migrations for compatibility and persisted shape;
- configuration and deployment for real composition and ownership;
- documentation and ADRs for rationale and intended restrictions;
- history for why an odd boundary exists and whether a transition is incomplete;
- telemetry names, logs, and operational scripts for failure and recovery assumptions.

Agreement across independent sources raises confidence. Disagreement is a finding. A test may encode
an obsolete limitation; an ADR may describe a migration target not yet implemented; production
configuration may expose coupling hidden by interfaces. Preserve the disagreement until evidence or
authority resolves it.

For each important conclusion, retain an evidence chain: path or commit, what it demonstrates, what
it does not demonstrate, and how it bears on the task. This keeps a persuasive interpretation from
quietly becoming a repository fact.

## Find implicit architecture

Messy repositories often express architecture indirectly. Look for:

- duplicated conditionals that reveal a policy with no named owner;
- the same data shape redefined across packages or languages;
- writes in several layers but reconciliation in only one;
- adapters that leak provider-specific behavior into orchestration;
- tests that always initialize components in a particular order;
- retry, timeout, or deduplication logic split between caller and worker;
- migrations or feature flags implying old and new semantics coexist;
- comments such as “must,” “never,” “temporary,” or “for compatibility” without a durable record;
- empty directories, absent tests, ignored errors, or dead code that contradict expected behavior.

Do not immediately promote these observations. Determine whether they are accidental duplication,
unfinished work, an implementation defect, or evidence of a durable decision.

## Investigate state over time

For stateful behavior, map:

- creation, identity, ownership, and authoritative storage;
- in-memory, browser, process, database, cache, queue, and external-provider copies;
- terminal versus non-terminal states and allowed transitions;
- reconstruction after restart or reconnection;
- concurrent writers, stale readers, and conflict resolution;
- expiration, cancellation, tombstones, cleanup, and migration;
- what is deliberately ephemeral and must not be restored.

Search for both the normal path and compensating behavior. A repository may implement persistence in
a startup loader, failure handler, migration, or polling loop rather than near the original write.

## Treat absence as evidence carefully

“There is no ADR,” “nothing verifies this,” or “the repository has no recovery path” are strong
claims. Before carrying one forward, record:

- directories and history inspected;
- exact symbols and conceptual aliases searched;
- generated, vendored, ignored, or external sources that were excluded;
- whether tests or operational behavior provide an implicit substitute;
- the exact tree on which the absence was observed.

An unsuccessful narrow search is not proof of absence. It is still useful as a bounded observation
when its limits are explicit.

## Stop progressively

Expand investigation only when new evidence could change implementation, durable-boundary judgment,
or verification. Stop when the requested behavior, relevant responsibility, relied-on promises,
state lifecycle, and meaningful uncertainty are understood well enough to act safely.

Do not bootstrap governance for an entire repository merely because it is old, inconsistent, or
poorly documented. Capture unresolved evidence as discoveries and let future work deepen the model
where demand appears.

## Record an archaeological finding

A useful finding contains an observation, exact-tree basis, relevance to current or future work,
alternative interpretations when needed, and a disposition. Keep descriptive evidence separate from
the normative conclusion. Resolution may establish durable governance, repair implementation, add tests
or documentation, schedule follow-up, split the question, or conclude that no artifact is needed.
