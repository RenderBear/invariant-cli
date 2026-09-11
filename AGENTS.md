# AGENTS.md

## Critical rules

- **Commit changes directly to local main.**
- **Never push to the remote.** No `git push` under any circumstances, publishing is the user's decision.
- **Repository-local skills are product source, not active agent skills.** Do not use `skills/intent-*` as an operating workflow unless the user explicitly asks you to run or test them.
- **Do not add migrations.** This repository does not need backward-compatibility or migration paths unless the user explicitly requests one; replace obsolete formats and locations directly.
- **Restrict tests to Git mechanics.** Retain or add tests only for repository setup, capability detection, isolated worktrees, exact-tree verification, atomic landing, concurrency, or remote publication. Do not test command presentation, conversations, documentation parity, prose wording, semantic policy, private non-Git helpers, browser behavior, or standalone styling utilities.

## Where things live

- **`protocol/protocol.md`** is the implementation-independent contract: tracked state, record
  envelopes, the task lifecycle and its actions, landing guarantees, commit trailers, and the JSON
  envelope with its outcomes and diagnostic codes. `protocol/model.html` is its human explanation.
  The folder is also published on its own through the `protocol` remote as a subtree.
- **`docs/SPEC.md`** is the design of record for this CLI implementation: commands, configuration,
  runtime layout, and mechanics. Where it disagrees with the protocol, the protocol governs and
  SPEC.md is wrong.
- **`docs/cli-basics.md`** is the human command reference; **`docs/design.md`** holds the document and
  terminal palette, glyphs, and layout rules only, with no rationale.
- A change to protocol behaviour is made in `protocol/protocol.md` first, then in the code and
  `docs/SPEC.md`.
