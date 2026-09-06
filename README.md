# Invariant

**Unsupervised, not ungoverned. A normative, git-grounded control plane for Claude Code, Cursor, and Codex.**

Invariant establishes and persists critical architectural artefacts through long running, complex agentic work.

At its core, Invariant is a memory and a gate:

- **Normative records.** Your architecture decisions and contracts, written as plain Markdown.
  A thin YAML index makes them retrievable by path, says who accepted them, which test witnesses
  them, and when to revisit. Decisions get superseded, never silently overwritten.
- **Git-grounded mechanics.** Each change gets its own worktree, gets verified as an exact git
  tree, and lands on the integration branch atomically — only after the affected checks pass and
  the affected decisions are reviewed. Pushing stays off unless the repo opts in.

And that pair is what makes it safe to hand agents the keys:

- **Governed autonomy.** Agents can move fast because the rules are written down and enforced.
  Routine changes land in two commands. Touch a recorded decision, and the lifecycle pauses until
  an agent — or you, if it lacks the authority — resolves it.
- **Guided planning and execution.** Run several tasks in one clone without them stepping on each
  other. Plans and leases keep concurrent agents out of each other's way, and a moved branch means
  a clean redo, not a clobbered one. Run it fully automatic, or approve each transition.

Invariant records who decided what, on which commit, with what evidence. It can't prove the
reviewer thought hard — but it can always show you who signed off, and on exactly what.

![A Git-grounded lifecycle carries a user goal through coordination, execution, verification, conflict resolution by an agent or human, and local landing. A durable semantic layer maps domains to architecture files and contracts to contract files.](.github/assets/lifecycle.svg)

## Install

Invariant is a standalone Python CLI. It contains no model and makes no network calls; your coding
agent provides the model and invokes `invariant` through its shell. It requires a Git with linked
worktrees and `merge-tree --write-tree` (probed before anything is written).

```bash
uv tool install git+https://github.com/RenderBear/invariant-cli.git
```

```bash
invariant --version
```

## Quick start

From your repository root:

```bash
invariant init
```

This writes `.invariant/config.yml` and installs a managed workflow block into your agent
instructions — `AGENTS.md` for Codex and Cursor, `CLAUDE.md` for Claude Code
([AGENTS.example.md](AGENTS.example.md) is a portable reference for other harnesses). Then work
normally:

**1. Establish the baseline.** Tell your agent:

```text
Run a full Invariant governance pass.
```

It investigates responsibilities, boundaries, and executable promises, saves the audit under
`.invariant/audits/`, and adopts the unambiguous findings as records. You don't need a complete
model up front — normal work deepens it progressively.

**2. Ask for changes as usual.** Just chat:

```text
Job recovery breaks when the browser restarts mid-run. Fix it.
```

The agent runs `invariant task begin`, implements in the worktree Invariant creates, and runs
`invariant task finish`. Routine changes land in those two commands. When a durable decision is
actually affected, `finish` returns typed actions; the agent resolves them within its authority
and escalates to you only when it can't.

You state goals and settle escalated conflicts. You never pick branches, author assessment files,
or inspect Invariant's internals — that surface belongs to the agent.

## Configuration

Without a configuration file, Invariant uses these defaults:

```yaml
version: 1
coding_agents: [codex, claude]  # which instruction files init manages
authority: agent                # who may accept durable records: agent | human
execution: auto                 # pause lifecycle transitions for approval: auto | assisted
integration_branch: auto        # landing target; auto = current branch at task begin
push_remote: off                # push the exact landed commit to the existing upstream: off | on
adapters:
  intent_brief: off             # optional intent-expansion and whole-candidate review hooks
```

Inspect or change validated settings with `invariant config show` and
`invariant config set <key> <value>`.

## What it adds to your repository

```text
your-repository/
├── .invariant/
│   ├── config.yml        optional configuration
│   ├── SEMANTICS.yml     thin index over canonical prose: authority, applicability, revisit, witnesses
│   ├── DOMAINS.yml       stable responsibilities and architecture pointers
│   ├── CONTRACTS.yml     executable promises between responsibilities
│   ├── audits/           saved investigations (evidence, not rules)
│   ├── discoveries/      open observations from ongoing work (evidence, not rules)
│   └── runtime/          self-ignored task state, worktrees, receipts, and archives
└── docs/
    └── architecture.md   ordinary Markdown remains the source of truth
```

Retrieve the records governing any path with
`invariant context semantics --path <path>` (text or JSON). Inspect finished work with
`invariant task status` and `invariant task evidence`.

## Learn more

- [CLI basics](docs/cli-basics.md) — human commands, a complete task walkthrough, and the
  agent-facing command groups.
- [SPEC.md](docs/SPEC.md) — the complete design of record: the semantic model, lifecycle, hook
  protocol, and safety rules.
