# Invariant: Scale agentic coding without architectural drift

Agent harnesses know how to reason, plan, dispatch, and resume. Git knows how to preserve exact
trees and move refs atomically. The dangerous gap is between them: deciding what concurrent agent
work may change, whether it still means what it intended to mean, and whether it can land without
overwriting another change.

Invariant is the repository-safety kernel for that gap. It does not replace your harness or Git. It
gives their handoff a durable contract: accepted architecture and authority live with the code;
write workers receive isolated worktrees; evidence and review bind to one exact candidate; and the
integration ref moves atomically or not at all.

![An agent harness owns reasoning, planning, worker dispatch, and implementation. Invariant sits between the harness and Git as a repository-safety kernel, owning coordination, isolation, authority, exact-tree verification, and atomic attested landing. Git supplies worktrees, immutable trees, branches, and atomic refs.](.github/assets/kernel.svg)

## More safe work in flight

Scale here is not the number of model calls. It is how much repository authority you can hand to
agents — across long-running sessions and genuinely parallel changes — without making a model's
memory or a conversation transcript the source of truth.

- **The harness owns intelligence and throughput.** Codex, Claude Code, an SDK, or an automation
  system investigates the repository, proposes a plan, dispatches workers, and implements changes.
- **Invariant owns repository consequences.** It validates claims and dependencies, isolates every
  writer, computes the actual reach of the resulting tree, obtains review within recorded authority,
  runs applicable checks, and controls landing.
- **Git owns exact state.** Commits and trees identify what was reviewed; linked worktrees separate
  writers; compare-and-swap makes the integration update atomic; trailers leave an attributable
  record in history.

A cohesive change remains one work item. A plan becomes parallel only when useful units have
concrete, non-overlapping claims. Ready units run together; a changed contract converges before its
consumers begin; then the combined candidate passes the same exact-tree review, verification, and
landing path as any other change.

If a check fails, a real conflict appears, or authority is missing, the work is retained and the
integration branch does not move. If another landing wins the race, the candidate is rebuilt and
reverified against the new head. Routine work continues; consequential work stops at an explicit
boundary.

## Quick start

Invariant uses an existing Codex or Claude Code installation and stores no
provider credentials or API keys. Initialization checks the native connection and can open its normal
sign-in flow when needed.

```bash
uv tool install git+https://github.com/RenderBear/invariant-cli.git
```

From a Git repository:

```bash
invariant init
```

Initialization asks for authority, execution, landing, and publication. Use `invariant init
--defaults` to accept the safe local policy without those questions. Failed provider
connections are warnings and automatic selection continues to the next provider. A single connected
provider is a complete setup; `invariant connect` inspects or changes machine-level connections.
If a complete configuration already exists, `init` warns before asking setup questions and lets you
keep it or replace every repository setting. Use `invariant set <key> <value>` for a single change.

Start working:

```bash
invariant start
```

Ask questions or request changes in that conversation. If `start` finds no configuration, it runs
guided initialization first and then continues. Establishment uses the same flow:

```bash
invariant establish
```

`establish` opens a durable conversation seeded with `:establish`. Under human authority it shows
the findings and exact proposal there; discuss it normally, then enter `:record` to accept. Publishing
is off by default.

Agent harnesses can call the same kernel directly over MCP. Each server is bound to one Git
repository; it exposes typed semantic, lifecycle, evidence, plan, and lease tools over stdio while
the versioned CLI command contract remains authoritative:

```bash
invariant-mcp --repository /absolute/path/to/repository
```

Configure that command in the harness as a local stdio MCP server. The MCP process keeps no
authoritative memory of its own: restarting it reconnects to the records, task state, and Git objects
owned by the repository.

## Bring your agent. Add only what you need.

Invariant owns the durable lifecycle; your provider owns the model account, authentication, quota, and
billing. Protected semantic reads and lifecycle transitions deliberately run with bounded tools and
authority.

The minimal setup needs no extras. Add grounding or choose a provider when the work calls for it:

```bash
invariant source add --url https://example.com/standards --repo
invariant set harness claude
```

- **Grounding sources** bring attributable external evidence into a repository, domain, or contract.
- **Another provider** is an available choice, not a missing dependency; the preference stays local to
  the clone and is never committed.

## The surface

| Need | Command |
| --- | --- |
| Inspect or connect a coding agent | `invariant connect [codex\|claude]` |
| Ask, change, inspect status, or resolve a decision | `invariant start [--session <id>]` |
| Open the read-only project and lifecycle explorer | `invariant serve` |
| Establish or refresh architecture in a conversation | `invariant establish` |
| Add scoped evidence | `invariant source add …` |
| Change a repository or clone preference | `invariant set <key> <value>` |

The human surface is exactly `init`, `connect`, `start`, `establish`, `serve`, `source`, and `set`.
The deterministic task, governance, evidence, coordination, and candidate engine stays behind that
surface. `invariant-mcp` is the typed harness surface over the same engine, not another lifecycle.

## Not another instruction file

An instruction file asks a model to behave. An Invariant record gives accepted meaning a stable
identity, scope, authority, invalidation rule, and—where the promise is observable—an executable
witness. Records are selected again from the accepted tree, checked against the exact candidate,
and bound into the landing commit.

That distinction matters. A prose constraint is still only as reliable as the reviewer interpreting
it. A policy or verifier enforced by the kernel does not depend on model obedience. For example,
`push_remote: off` prevents Invariant from publishing at all; when publication is enabled, the
landing code still permits only the exact landed commit and the integration branch's existing
upstream. The semantic record explains why that boundary exists and makes changes to it
consequential. The mechanics enforce it.

Invariant cannot revoke a separate capability the harness already granted. A worker with remote
credentials and unrestricted network access can still run `git push` outside the lifecycle. For a
hard publication boundary, workers must lack that capability and only the configured Invariant
landing process may hold it.

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
