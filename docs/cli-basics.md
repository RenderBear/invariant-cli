# Invariant CLI basics

Invariant has seven human-facing commands:

```text
init  connect  start  establish  serve  source  set
```

Questions, changes, status, recovery, and authority decisions happen inside a durable `start`
conversation. The user is never asked to operate task IDs, worktrees, review files, or lifecycle
commands.

## Connect a coding agent

Invariant uses an existing Codex or Claude Code installation and stores no provider credentials.

```bash
invariant connect
invariant connect codex
invariant connect claude
invariant connect --default codex
```

Without an argument, `connect` reports both providers and the machine default. With a provider it
opens that tool's native sign-in flow when needed. `--default` also changes the machine preference.
A repository-specific choice can be made later with `invariant set harness codex|claude|auto`.

## Initialize a repository

```bash
invariant init
```

Interactive setup asks four questions: who has authority over repository meaning, whether valid
local transitions run automatically, which branch receives landed work, and whether successful
landings are published to an existing upstream. There is no adapter question and the tracked
configuration contains no adapter registry.

Use the defaults without the questionnaire:

```bash
invariant init --defaults
```

On a clean repository, initialization commits its deterministic configuration locally. Existing
provider instructions such as `AGENTS.md` and `CLAUDE.md` are untouched. Running `init` again offers
to keep the complete configuration or replace it; `set` is the normal way to change one preference.

Initialization is optional ceremony. If `start` or `establish` finds no configuration, it runs the
same guided setup, takes the user's choices, and then continues into the requested conversation.

## Work through one conversation

```bash
invariant start
invariant start "Explain how restart recovery is owned"
invariant start --session <session-id>
```

A new conversation can answer questions and route requested writes through Invariant's managed
lifecycle. The agent remains read-only while interpreting the user's message. When a write is
needed, Invariant creates an isolated worktree, checks the exact candidate against accepted records,
verifies it, and lands it atomically on the configured local branch.

Sessions are durable files in the local workspace. They retain a theme, transcript, and opaque
provider handle without becoming repository authority. Useful conversation controls are:

| Control | Effect |
| --- | --- |
| `:new [theme]` | Create and enter another durable session. |
| `:sessions` | List sessions in this project. |
| `:switch ID` | Return to a listed session. |
| `:status` | Show deterministic repository and lifecycle status. |
| `:settings` | Show repository and clone preferences. |
| `:set KEY VALUE` | Change one preference. |
| `:source add ...` | Add one scoped grounding source. |
| `:establish` | Inspect and prepare durable repository records. |
| `:record` | Accept the exact pending record proposal. |
| `:exit` | End the console while preserving the session. |

## Establish repository records

```bash
invariant establish
```

This is composition, not a separate interaction model. `establish` starts a normal durable session
themed “Repository records” and seeds it with `:establish`.

With agent authority, the audit, delegated authority review when needed, projection, checking, and
landing continue automatically. Repository policy is the exception: if the establishment candidate
changes `.invariant/config.yml`, or covers earlier unattested history that did, Invariant keeps agent
authority for the record choices and asks the user only to attest that policy boundary. With human
authority, the complete proposal requires the same user acceptance.

Whenever acceptance is needed, the conversation shows a compact summary and writes a readable
`.invariant/runtime/tasks/<task-id>/review.md` containing the reason, findings and evidence,
projected records, changed files, verification results, and exact candidate tree. The user can
discuss it for as long as needed. Discussion does not accept or mutate it; entering `:record`
accepts that exact candidate with user authority and continues landing. If the candidate changes,
Invariant presents a new review instead of carrying the acceptance forward.

Leaving the conversation preserves the proposal. Running `establish` later resumes the newest
compatible attempt in another durable conversation. When unfinished establishment work exists, the
conversation first shows when it was last saved and whether its captured Git ground and mechanics
are current, advanced, or stale. A yes-or-no prompt lets the user continue it or start fresh; Invariant
never chooses silently.

## Add grounding evidence

```bash
invariant source add --url https://example.com/api.json --scope contract:payments-api
invariant source add --path sources/backend.md --scope domain:backend
invariant source add --url https://example.com/standards --repo
```

`--path` is relative to `.invariant/` and must remain beneath `.invariant/sources/`. `--scope`
accepts an established `domain:<id>` or `contract:<id>`; a natural-language description may be
resolved to one existing scope. `--repo` applies throughout the repository. Source material is
always untrusted evidence: it cannot create records or grant authority by itself.

## Change preferences

```bash
invariant set authority human
invariant set execution auto
invariant set integration_branch main
invariant set push_remote off
invariant set harness claude
```

The first four values are tracked repository policy. `harness` and the optional session `mode` are
clone-local preferences. Selecting a concrete harness also runs its native connection flow if needed.
Adapters are intentionally absent from configuration; a future `invariant add adapter` command can
introduce that extension explicitly.

## View state in the browser

```bash
invariant serve
```

The loopback browser is a read-only state and lifecycle explorer. Registered repositories appear as
folders and their sessions as files in one explorer pane. The detail pane shows repository state,
lifecycle work, evidence, and the selected session log. It cannot create sessions, send messages,
change settings, or advance work.

Use `invariant serve --port <port>` when port 3000 is occupied. Project registrations, transcripts,
and provider handles live in the user's local Invariant workspace and carry no semantic authority.
