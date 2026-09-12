# Invariant

A governance layer for agentic work. You say what should change. Agents do the work in parallel.
Invariant decides what work is admissible, keeps accepted repository meaning in front of every
agent, verifies the exact result, and lands it in Git with a full account of who authorized what.

![Intent comes from the user. Resolution stays with the user or is narrowly delegated to a secondary agent. Normative contracts, ADRs, and specs form the semantic kernel. Execution fans out as parallel work inside a Git-grounded lifecycle.](.github/assets/kernel.svg)

| Layer | Owner or ground |
|---|---|
| **Intent** | The user, always. A provider run cannot supply it. |
| **Resolution** | The user, or a secondary agent holding one scoped `intent.resolve` capability for one question |
| **Semantic kernel** | Domain, contract, semantic, and constraint records accepted in the repository |
| **Lifecycle** | Git objects, refs, trees, evidence, and atomic ref movement |
| **Execution** | Isolated agent work inside the kernel's admissible frontier |

Execution is always an agent's. Authority never is. A provider gains no semantic standing from its
ability to edit files, a review is not an acceptance, and a record's authority is whatever landing
accepted it, not what its author wrote. The kernel is deterministic: it selects the records a change
reaches, recommends a bounded work shape, issues one-consequence capabilities, retains every attempt
on a Git ref, verifies the exact candidate, and moves the integration ref by compare-and-swap or not
at all. Everything a human sees is a projection of that ledger.

Two hosts sit on the same application boundary. The interactive console below is one. The
repository-bound MCP server is the other, for a harness that is itself the model:

```bash
invariant-mcp --repository /absolute/path/to/repository
```

## A change, start to finish

```console
$ invariant start

█ █▄ █ █ █ ▄▀▄ █▀▄ █ ▄▀▄ █▄ █ ▀█▀
█ █ ▀█ ▀▄▀ █▀█ █▀▄ █ █▀█ █ ▀█  █    conversation

  codex  ·  change mode  ·  session s-21f6c830ab
  :help for commands  ·  Ctrl-C to leave

(change) › update the call structure of the retry client so callers pass a policy
           object instead of three keyword arguments
(codex) › 41s

  Split the work into two units: the retry client and its contract in
  src/jobs/retry, and the three call sites in src/workers. The contract's
  verifier passed and the independent review accepted the candidate.

  Change   session-21f6c830ab-7d4c1a90d2e8
  Files    src/jobs/retry.py · schemas/retry-policy.json · src/workers/ingest.py ·
           src/workers/notify.py · src/workers/reindex.py
  Commit   9c4da83816c8
  Status   landed
```

What happened underneath, in order:

1. The coordinator turn is read-only. It classified the message as a change and named its reach
   estimate: `src/jobs/retry`, `schemas`, `src/workers`. A reply that names no reach is refused, not
   widened to the repository.
2. Invariant opened a durable change ledger in Git, bound the message as `user:` intent, and
   selected the records that reach touches: the `jobs.retry` domain, the `retry.policy.v1` contract
   whose surface is `schemas/retry-policy.json`, and the semantic record on retry ownership.
3. The provider answered one planning question over that selected context: does this intent split
   into contractually independent units? It proposed a provider unit for the contract and a
   consumer unit for the workers that depends on it. Invariant validated the proposal, derived the
   conflict graph, and recorded the recommendation.
4. The provider unit ran in its own worktree with the domain's responsibility, the contract's
   assertion, and the required verifier in its prompt. When it converged, the consumer unit started
   from that converged candidate, never from the stale base.
5. Invariant checked each unit's actual diff against its claims, built one exact candidate tree,
   ran the contract's verifier against it, and opened the independent review the contract requires.
6. A fresh provider run, distinct from both authors, reviewed the exact tree. Landing consumed one
   single-use grant and moved `main` by compare-and-swap. The commit carries the intent digest,
   the plan, every unit's tree and actor, every decision, the governance versions, the evidence
   digest, and the review.

Had the review been assigned to you instead, the turn would have ended with the resolution list:

```text
1. Independent review of the exact candidate · resolver: user
   Intent: update the call structure of the retry client …
   Candidate: 3f2a9c1e8b04 touching 5 paths

Type :resolve N accept|reject [note] to answer one item.
Type :accept to accept every remaining item and land.
Type :details to inspect the records, rules, and Git identity.
```

## Get a project online

```bash
uv tool install git+https://github.com/RenderBear/invariant-cli.git
cd your-project
invariant init
invariant establish
```

`init` is guided setup: who resolves bound questions, whether publication may be requested, and
which connected agent sessions prefer. `invariant init --defaults` takes the safe local policy
without questions. It creates and commits `.invariant/config.yml` itself and registers the
repository in your local workspace.

`establish` opens a durable governance-baseline session. The connected agent inspects the
repository and drafts only evidence-backed domain, contract, semantic, and constraint records plus
the audit that motivated them. Invariant validates the exact candidate. With the default
`secondary-agent` policy a fresh independent agent accepts the baseline; the drafting agent cannot
accept its own work, and a review never stands in for acceptance. With resolution assigned to you,
the session shows a plain-language decision brief and the resolution list instead of record YAML.
Policy changes are direct user decisions in either mode, and a record you accepted can only be
revised or retired with your resolution.

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

Start a session, resume one later, or move between several. Each keeps its own theme, transcript,
agent, and native provider thread:

```bash
invariant start
invariant start "Explain the payment boundary"
invariant start --using claude --theme "Payment retries"
invariant start --session s-21f6c830ab
```

Inside the conversation:

```text
:new [theme]                     create another session
:sessions                        list this project's sessions
:switch ID|N                     switch sessions
:agent codex                     switch this session's coding agent
:mode ask|change                 choose question-only or change-capable turns
:status                          inspect project and governance state
:settings                        inspect policy and local preferences
:set KEY VALUE                   change one setting
:establish [focus]               draft or reconcile the governance baseline
:pending [CHANGE]                list what you must resolve
:resolve N accept|reject [note]  answer one item of that list
:details [CHANGE]                inspect the pending governance decision
:accept [CHANGE]                 answer every remaining item and land
:exit                            leave without losing the session
```

Direct user authority exists only at an interactive terminal outside runtime worktrees. A provider
run, a piped console, or the MCP server cannot supply intent or resolve an item, and every ledger
event records how its principal was bound.

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
invariant set resolution user
invariant set publication on
invariant set parallelism 4
```

`harness` and `mode` are clone-local. A tracked policy setting is different: `set` constructs one
deterministic config candidate in an isolated worktree, binds the command as direct user intent,
verifies it, lands it with an Invariant attestation, and cleans up. It runs only from the
interactive host. Convenience does not turn mutable config into accepted authority.

## One workspace for every session

```bash
invariant serve
```

The loopback workspace shows every registered repository as a folder and every durable session as a
session file. It updates while consoles run and shows transcripts, current changes, record count,
validation, and audit freshness. The web surface is deliberately read-only.

## Read further

- [CLI basics](docs/cli-basics.md)
- [Visual design language](docs/design.md)
- [CLI implementation design](docs/SPEC.md)
- [Protocol overview](protocol/README.md)
- [Normative protocol](protocol/protocol.md)
- [Human protocol model](protocol/model.html)
