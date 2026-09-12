# Invariant CLI basics

The CLI is a visual local host over the v1 protocol. It owns setup, agent connections, durable
conversations, and the read-only workspace. Git refs and objects remain the authority for repository
work; transcripts and provider handles remain local presentation state.

The human surface is:

```text
init  status  start  establish  connect  set  serve
```

## Initialize a project

```bash
invariant init
```

Guided setup asks how semantic resolution may be delegated, whether valid transitions continue
automatically, whether publication can be requested, and which connected agent new sessions prefer.
The user remains the intent supplier. `invariant init --defaults` chooses the safe defaults without
questions.

Initialization commits `.invariant/config.yml` as one deterministic bootstrap commit and registers the
project in the per-user workspace. It performs its own staging; there is no `git add` step. Running
it again keeps the accepted policy and points to `invariant establish` to reconcile governance.

## Establish governance

```bash
invariant establish
invariant establish --using claude
```

`establish` creates a durable `Governance baseline` session and runs the same operation as the
in-session `:establish` control. A read-only coordinator inspects the repository first. When the
accepted baseline is absent or stale, an execution agent drafts a minimal, evidence-backed audit
and record set in an isolated worktree. It may create semantic, domain, contract, and constraint
records, but it must not create a record merely to fill a category.

Invariant resolves every locator, validates the candidate record grammar and closed directives,
captures exact-tree evidence, and presents the resulting candidate. The candidate remains pending
until the user types `:accept`; neither the drafting agent nor a delegated resolver can establish
governance. If the current records already describe the repository, the coordinator reports that
there is no change to accept.

## See project state

```bash
invariant status
invariant --format json status
```

Status combines repository truth with local host state. It shows the integration branch, validation
state, intent source, resolution delegation, parallel execution policy, Git-grounded lifecycle,
accepted semantic-kernel record count, latest audit, audit staleness, and the project's durable and
currently live sessions.

## Connect an agent

Invariant uses an existing Codex or Claude Code installation and stores no provider credentials.

```bash
invariant connect
invariant connect codex
invariant connect claude
invariant connect --default codex
```

Without a provider, the command reports installation and native authentication state. A repository
can follow the machine default or select a clone-local preference with `invariant set harness`.

## Start a durable conversation

```bash
invariant start
invariant start "Explain the recovery boundary"
invariant start --session s-ab12cd34ef
invariant start --using claude --theme "Payment retries"
```

Each session has a stable Invariant id, theme, transcript, selected provider, and opaque native
provider handle. The transcript survives console exit and appears in `status` and `serve`, but it is
not repository authority.

The session controls are:

| Control | Effect |
| --- | --- |
| `:new [theme]` | Create and enter another session. |
| `:sessions` | List this project's sessions. |
| `:switch ID` | Switch to a listed session; an ordinal also works. |
| `:agent codex\|claude` | Switch this session's provider and start a new native provider thread. |
| `:mode ask\|change` | Choose question-only or change-capable classification. |
| `:status` | Show sessions and governance freshness. |
| `:settings` | Show tracked policy and clone-local preferences. |
| `:set KEY VALUE` | Apply the same one-setting operation as `invariant set`. |
| `:establish [focus]` | Draft or reconcile the repository governance baseline. |
| `:accept [CHANGE]` | Accept one exact pending governance candidate with direct user authority. |
| `:exit` | Leave while preserving the session. |

Conversation turns are read-only while the provider interprets the message. When a change is
requested, the host uses the original user message as intent, opens a durable change, obtains an
isolated worktree for the provider principal, commits the provider's candidate, runs compiled
verification, obtains a separate review when required, and lands atomically. If the candidate
changes governance, it remains pending until `:accept`.

## Change one setting

Clone-local preferences update immediately:

```bash
invariant set harness codex
invariant set mode change
```

Tracked policy changes use the governed lifecycle:

```bash
invariant set resolution secondary-agent
invariant set execution assisted
invariant set publication on
invariant set parallelism 4
```

The shorthand deterministically constructs exactly one config candidate, obtains direct user
acceptance from the invoking CLI principal, verifies and lands it, then removes disposable attempt
refs. It never treats mutable primary-worktree config as policy. Changing to another integration
branch is deliberately blocked until the required atomic ref transition has a protocol design.

## Open the global workspace

```bash
invariant serve
invariant serve --port 3100
invariant serve --project /path/to/another/repository
```

The foreground service binds only to `127.0.0.1`. It shows every explicitly registered project,
their durable sessions, live console presence, transcripts, lifecycle changes, governance state,
and audit freshness. The browser and HTTP API are read-only; only GET and HEAD are accepted.

## Harness protocol

```bash
invariant-mcp --repository /absolute/path/to/repository --principal harness:local
```

The repository-bound MCP gateway is the typed automation surface. It exposes governance,
recommendation, action, capability, isolated-work, candidate, verification, landing, and publication
operations without offering a generic shell or accepting a repository path per call.
