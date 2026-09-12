# Invariant protocol

Invariant is a protocol for building a governance layer around agentic work. The reference
implementation lives at [RenderBear/invariant-cli](https://github.com/RenderBear/invariant-cli).

```text
governance layer = semantic kernel + Git-grounded lifecycle
```

The [normative protocol](protocol.md) defines the contract. The
[human model](model.html) explains its objects and boundaries.

## Semantic kernel

The kernel selects accepted repository meaning and compiles only a closed vocabulary of
consequences. Prose remains open; it does not become an implicit permission language.

Authority is not a single mode:

- **intent supply** is an attributable desired-state statement or accepted promise; and
- **resolution capability** is permission to answer one exact semantic action within that intent.

`intent.resolve` may be passed to a model when policy delegates that action. The response remains
schema-bound and causally validated. It cannot widen intent, change policy, or authorize execution.

## Git-grounded lifecycle

Execution uses a separate capability class. Worktree creation, writes, verifier runs, candidate
convergence, integration, publication, invalidation, and destructive cleanup each have their own
closed capability.

Ledgers under `refs/invariant/changes/*` bind intent, governance, recommendations, decisions,
grants, attempts, evidence, actions, and outcomes. Work and candidates remain reachable through
dedicated refs. Landing verifies one exact candidate and compare-and-swaps the integration ref.

## Protocol rule

> Open semantics, closed consequences.

Evidence never becomes authority merely because it was retrieved or produced by a model. Execution
access never becomes authority because an actor can call a tool. Intent supply never becomes
execution access because its supplier can decide.

JSON envelopes carry literal protocol version `1`. There is no version negotiation.
