# Invariant protocol

The contract between a repository, the durable records it carries, and the agents that change it.
This folder defines the protocol; the reference CLI at
[RenderBear/invariant-cli](https://github.com/RenderBear/invariant-cli) implements it.

| File | What it is |
| --- | --- |
| [`protocol.md`](protocol.md) | The normative contract: tracked state, record envelopes, task lifecycle and actions, candidate verification and atomic landing, commit trailers, the JSON envelope, outcomes, and diagnostic codes. |
| [`model.html`](model.html) | The explanatory model for humans: what a record, evidence, and change are, who holds authority, and which guarantees hold. |

The protocol is versioned by the `protocol` field of every JSON response. The current version is 1.
There is no negotiation and no compatibility layer: an implementation emits exactly one version, and a
consumer checks the field before parsing.

The CLI's own design of record, `docs/SPEC.md` in the CLI repository, describes commands, configuration,
runtime layout, and mechanics of that implementation. Where it and `protocol.md` disagree, the protocol
governs.

This folder is tracked inside the CLI repository under `protocol/` and published on its own at
[RenderBear/invariant-protocol](https://github.com/RenderBear/invariant-protocol) as a subtree.
