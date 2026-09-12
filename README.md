# Invariant

Chat with coding agents in durable project sessions. Let them work in parallel. Keep intent,
governance, and Git consequences visibly separate.

```console
$ invariant start

█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀
█ █ ▀█ ▀▄▀ █▀█ █▀▄ █ █▀█ █ ▀█  █    conversation

  codex  ·  change mode  ·  session s-21f6c830ab
  :help for commands  ·  Ctrl-C to leave

(change) › make retry ownership explicit
(codex) › 18s

  Updated the recovery contract and its implementation.

  Change   session-21f6c830ab-7d4c1a90d2e8
  Files    docs/recovery.md · src/jobs/retry.py
  Commit   9c4da83816c8
  Status   landed
```

The conversation is the front door. Invariant turns requested writes into isolated, attributable
Git work: the provider never gains semantic authority just because it can edit files, and the user
never has to operate worktree ids, grant tokens, staging, or landing commands.

## Get a project online

```bash
uv tool install git+https://github.com/RenderBear/invariant-cli.git
cd your-project
invariant init
invariant establish
```

`init` is guided setup. Use `invariant init --defaults` for the safe local policy without questions.
It creates and commits `.invariant/config.yml` itself—there is no manual `git add` step—and registers
the repository in your local Invariant workspace.

`establish` opens a durable governance-baseline session. The connected agent inspects the
repository and drafts only evidence-backed semantic, domain, contract, and constraint records plus
the audit that motivated them. Invariant validates the exact candidate. With the default
`secondary-agent` resolution policy, a fresh independent agent reviews and accepts the baseline;
the drafting agent cannot accept its own work.

If setup assigned resolution to you, Invariant shows a short decision brief instead of record YAML
and protocol internals:

```text
6 records will define how Invariant understands and governs this repository.
…
Type :accept to establish it.
Type :details to inspect every record, rule, source, and the Git identity.
```

Policy changes remain direct user decisions in either mode.

```console
$ invariant status
  Repository

╭────────────────────────────────────────────────────╮
│                                                    │
│  Status       valid                                │
│  Project      checkout                             │
│  Branch       main                                 │
│  Sessions     3 total · 1 live                     │
│  Intent       user                                 │
│  Resolution   secondary-agent                      │
│  Semantic kernel  12 accepted records              │
│  Execution    parallel agents                      │
│  Lifecycle    Git-grounded                         │
│  Staleness    fresh                                │
│  Last audit   audit-20260912T091500Z               │
│                                                    │
╰────────────────────────────────────────────────────╯
```

## Durable conversations

Start a new session, resume one later, or move between several while they retain their own theme,
transcript, agent, and native provider thread:

```bash
invariant start
invariant start "Explain the payment boundary"
invariant start --using claude --theme "Payment retries"
invariant start --session s-21f6c830ab
```

Inside the conversation:

```text
:new [theme]       create another session
:sessions          list this project's sessions
:switch ID|N       switch sessions
:agent codex       switch this session's coding agent
:mode ask|change   choose question-only or change-capable turns
:status            inspect project and governance state
:settings          inspect policy and local preferences
:set KEY VALUE     change one setting
:establish [focus] draft or reconcile the governance baseline
:details [CHANGE]  inspect a pending human governance decision
:accept [CHANGE]   accept when resolution is assigned to you
:exit              leave without losing the session
```

Invariant uses an existing Codex or Claude Code installation and keeps authentication, billing, and
model choice with that provider:

```bash
invariant connect
invariant connect codex
invariant connect --default claude
```

## One setting, still governed

```bash
invariant set harness codex
invariant set resolution secondary-agent
invariant set execution assisted
invariant set publication on
invariant set parallelism 4
```

`harness` and `mode` are clone-local. A tracked policy setting is different: `set` constructs one
deterministic config candidate in an isolated worktree, binds the command as direct user intent,
verifies it, lands it with an Invariant attestation, and cleans up. Convenience does not turn mutable
config into accepted authority.

## One workspace for every session

```bash
invariant serve
```

The loopback workspace shows every registered repository as a folder and every durable session as a
session file. It updates while consoles run and shows transcripts, current changes, record count,
validation, and audit freshness. The web surface is deliberately read-only.

## What is underneath the surface

![Intent comes from the user. Resolution stays with the user or is narrowly delegated to a secondary agent. Normative contracts, ADRs, and specs form the semantic kernel. Execution fans out as parallel work inside a Git-grounded lifecycle.](.github/assets/kernel.svg)

| Layer | Owner or ground |
|---|---|
| **Intent** | User |
| **Resolution** | User, or a secondary agent holding one scoped `intent.resolve` capability |
| **Semantic kernel** | Normative contracts, ADRs, and specs accepted in the repository |
| **Lifecycle** | Git objects, refs, trees, evidence, and atomic ref movement |
| **Execution** | Isolated agent work within the kernel's admissible graph |

The terminal host is visual and conversational. The kernel remains deterministic: it selects
accepted records, recommends bounded work, issues one-consequence capabilities, retains attempts on
Git refs, verifies exact candidates, and moves the integration ref atomically.

Automation uses the same application boundary through the repository-bound MCP server:

```bash
invariant-mcp --repository /absolute/path/to/repository
```

## Read further

- [CLI basics](docs/cli-basics.md)
- [Visual design language](docs/design.md)
- [CLI implementation design](docs/SPEC.md)
- [Protocol overview](protocol/README.md)
- [Normative protocol](protocol/protocol.md)
- [Human protocol model](protocol/model.html)
