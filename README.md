# Invariant: Scale agentic coding without architectural drift

Agents rarely break architecture in one dramatic change. It drifts through individually reasonable
changes made from partial context.

Invariant is the write side of intent. The decisions, responsibilities, contracts, and sources a
team has accepted live in the repository as records, versioned with the code, and every
consequential change passes checkpoints that read them before it lands. The agent reasons freely;
the checkpoints give it something exact to reason against, and the landing attests back into the
same memory. The [protocol](protocol/README.md) defines that memory and its guarantees; this CLI
runs the lifecycle.

## What a change goes through

![Durable memory constrains a fixed lifecycle from goal through receipt, isolated worktree, exact candidate, evidence, review within authority, and atomic landing, with many changes running it in parallel in one clone.](.github/assets/lifecycle.svg)

- **Bounded autonomy.** `invariant change` plans and implements in an isolated worktree, commits an
  exact candidate, checks it against accepted records, and lands it on the local branch, so routine
  changes land in two commands. Touching a recorded decision pauses the lifecycle until an agent
  — or you, when it lacks the authority — resolves it. Rewriting accepted governance or defining a
  contract requires a fresh second-agent review unless a human accepts the exact candidate.
- **Scaled coordination.** Several changes run in one clone without stepping on each other, because
  each owns its worktree, receipt, and evidence, and landings serialize atomically on the integration
  branch.
- **Planning.** Plans and reserved work keep concurrent agents out of each other's way, and a moved
  branch means a clean re-verification, not a clobbered landing.

Architecture can evolve. It cannot drift silently.

## Start

Invariant is a local Python CLI. It uses an existing Codex or Claude Code installation and stores no
provider credentials or API keys. Initialization checks the native connection and can open its normal
sign-in flow when needed.

```bash
uv tool install git+https://github.com/RenderBear/invariant-cli.git
```

From a Git repository:

```bash
invariant init
```

Initialization asks for authority, execution, landing, publication, and optional intent-review
policy, then ends with one yes-or-no choice to establish durable records. Use
`invariant init --defaults` to accept the safe local policy without those questions. Failed provider
connections are warnings and automatic selection continues to the next provider. A single connected
provider is a complete setup; `invariant connect` inspects or changes machine-level connections.
If a complete configuration already exists, `init` warns before asking setup questions and lets you
keep it or replace every repository setting. Use `invariant set <key> <value>` for a single change.

If you defer establishment:

```bash
invariant establish
```

Then work normally:

```bash
invariant ask "Explain how job recovery is owned"
invariant change "Job recovery breaks after restart; fix it"
invariant status
```

`change` runs the lifecycle above and lands on the local branch. Publishing is off by default.

## Bring your agent. Add only what you need.

Invariant owns the durable lifecycle; your provider owns the model account, authentication, quota, and
billing. Protected semantic reads and lifecycle transitions deliberately run with bounded tools and
authority.

The minimal setup needs no extras. Optional add-ons are there when the work calls for them:

```bash
invariant source add --url https://example.com/standards --repo
invariant set adapters.intent_brief on
invariant set harness claude
```

- **Grounding sources** bring attributable external evidence into a repository, domain, or contract.
- **Intent review** expands ambiguous requests and reviews the exact candidate before landing.
- **Another provider** is an available choice, not a missing dependency; the preference stays local to
  the clone and is never committed.

## The surface

| Need | Command |
| --- | --- |
| Ask a read-only repository question | `invariant ask "…"` |
| Run one managed change | `invariant change "…"` |
| Keep a foreground conversation, optionally with the local observer | `invariant start [--server]` |
| Establish or refresh architecture | `invariant establish` |
| See state or configuration | `invariant status`, `invariant settings` |
| Add scoped evidence | `invariant source add …` |

The ordinary surface stays small. The deterministic task, governance, evidence, coordination, and
candidate protocol remains available to automation and recovery tooling through
`invariant help protocol`.

## What persists

```text
.invariant/
├── config.yml       repository policy
├── SEMANTICS.yml    accepted prose records, authority, applicability, and witnesses
├── DOMAINS.yml      stable responsibilities and architecture pointers
├── CONTRACTS.yml    executable promises between responsibilities
├── SOURCES.yml      grounding-source origins and scopes
├── audits/          saved investigations: evidence, not rules
└── runtime/         self-ignored task state, worktrees, receipts, and archives
```

The YAML is a thin envelope; the Markdown it points at stays canonical. Runtime layout, Git-root
resolution, and worktree mechanics are in [SPEC.md](docs/SPEC.md).

## Read further

- [Protocol overview](protocol/README.md) — the memory model, its four registries, and the operating philosophy.
- [Explanatory model](protocol/model.html) — the architecture, authority model, and guarantees.
- [Protocol](protocol/protocol.md) — the implementation-independent contract: state, lifecycle, landing, and the JSON envelope.
- [CLI basics](docs/cli-basics.md) — complete commands and a task walkthrough.
- [Design language](docs/design.md) — the document and terminal palette, glyphs, and layout rules.
- [SPEC.md](docs/SPEC.md) — the exhaustive design of record for this CLI implementation.
