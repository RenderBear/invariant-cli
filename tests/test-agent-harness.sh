#!/bin/sh
# Verify the optional harness connects schema-bound Invariant actions to local agents.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
agent="$root/bin/invariant-agent"
fixtures=$(mktemp -d "${TMPDIR:-/tmp}/invariant-agent-harness.XXXXXX")
fake_bin="$fixtures/bin"
mkdir -p "$fake_bin"
cleanup() { rm -rf "$fixtures"; }
trap cleanup EXIT HUP INT TERM

die() { echo "not ok - $1"; exit 1; }
ok() { echo "ok - $1"; }

new_repo() {
  destination=$1
  mkdir -p "$destination/.invariant"
  git -C "$destination" init -qb main
  git -C "$destination" config user.name test
  git -C "$destination" config user.email test@example.com
  git -C "$destination" config commit.gpgsign false
  cat >"$destination/.invariant/config.yml" <<'EOF'
version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
EOF
  printf 'seed\n' >"$destination/app.txt"
  git -C "$destination" add -A
  git -C "$destination" commit -qm seed
}

cat >"$fake_bin/codex" <<'EOF'
#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli test'
  exit 0
fi
printf '%s\n' "$*" >"$FAKE_AGENT_LOG"
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output=$1
  fi
  shift
done
[ -n "$output" ] || exit 3
cat >"$FAKE_AGENT_STDIN"
printf '%s\n' "$FAKE_AGENT_RESPONSE" >"$output"
printf '%s\n' '{"type":"thread.started","thread_id":"codex-test-session"}'
printf '%s\n' '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}'
EOF
chmod +x "$fake_bin/codex"

cat >"$fake_bin/claude" <<'EOF'
#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'claude-code test'
  exit 0
fi
printf '%s\n' "$*" >"$FAKE_AGENT_LOG"
cat >"$FAKE_AGENT_STDIN"
printf '{"session_id":"claude-test-session","usage":{"input_tokens":3},"structured_output":%s}\n' \
  "$FAKE_AGENT_RESPONSE"
EOF
chmod +x "$fake_bin/claude"

doctor=$(PATH="$fake_bin:$PATH" "$agent" --format json doctor)
printf '%s\n' "$doctor" | grep -q '"provider":"codex","available":true' ||
  die "doctor did not discover Codex"
printf '%s\n' "$doctor" | grep -q '"provider":"claude","available":true' ||
  die "doctor did not discover Claude Code"
ok "doctor reports installed local agent connections"

missing=$(INVARIANT_CODEX="$fixtures/missing-codex" "$agent" doctor codex)
printf '%s\n' "$missing" | grep -q '^NEXT: codex — .*INVARIANT_CODEX=' ||
  die "doctor did not explain how to configure a missing Codex executable"
ok "doctor gives an actionable provider-discovery hint"

conversation="$fixtures/conversation"
new_repo "$conversation"
ask_log="$fixtures/ask.args"
ask_stdin="$fixtures/ask.stdin"
response='{"message":"Hello from Codex."}'

answer=$(cd "$conversation" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$ask_log" FAKE_AGENT_STDIN="$ask_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" ask --using codex "Hi")
[ "$answer" = "Hello from Codex." ] || die "ask did not print the provider answer directly"
grep -q 'Request kind: ask' "$ask_stdin" ||
  die "Codex did not receive the direct repository question"
grep -q -- '--sandbox read-only' "$ask_log" ||
  die "ask did not preserve the Codex read-only boundary"

ask_preview_log="$fixtures/ask-preview.args"
preview=$(cd "$conversation" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$ask_preview_log" FAKE_AGENT_STDIN="$ask_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" ask --using codex --dry-run "Hi")
printf '%s\n' "$preview" | grep -q '^STATUS: preview$' ||
  die "ask dry-run did not print a preview"
[ ! -e "$ask_preview_log" ] || die "ask dry-run invoked Codex"
ok "ask provides a direct read-only conversation with an optional dry-run"

if missing_task=$(cd "$conversation" && PATH="$fake_bin:$PATH" \
  "$agent" task respond Hi --using codex --apply 2>&1); then
  die "a prompt-shaped missing task was accepted"
fi
printf '%s\n' "$missing_task" | grep -q 'invariant-agent ask --using codex "Hi"' ||
  die "missing task error did not redirect the user to ask"
ok "the low-level task command redirects prompt-shaped input to ask"

governance="$fixtures/governance"
new_repo "$governance"
(cd "$governance" && "$cli" source add --url https://example.com/reference --repo >/dev/null)
(cd "$governance" && "$cli" governance begin harness-audit >/dev/null)
codex_log="$fixtures/codex.args"
codex_stdin="$fixtures/codex.stdin"
response='{"version":1,"findings":[]}'

preview=$(cd "$governance" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$codex_log" FAKE_AGENT_STDIN="$codex_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" governance audit harness-audit --using codex)
printf '%s\n' "$preview" | grep -q '^STATUS: preview$' ||
  die "audit did not default to a non-mutating preview"
[ ! -e "$codex_log" ] || die "preview invoked Codex"
status=$(cd "$governance" && "$cli" governance status harness-audit)
printf '%s\n' "$status" | grep -q '^GOVERNANCE-PHASE: audit$' ||
  die "audit preview changed governance state"

applied=$(cd "$governance" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$codex_log" FAKE_AGENT_STDIN="$codex_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" governance audit harness-audit \
  --using codex --apply)
printf '%s\n' "$applied" | grep -q '^SESSION: codex-test-session$' ||
  die "Codex session attribution was not reported"
printf '%s\n' "$applied" | grep -q '^STATUS: submitted$' ||
  die "Codex result was not submitted"
grep -q -- '--sandbox read-only' "$codex_log" ||
  die "Codex was not constrained to its read-only sandbox"
grep -q -- '--ignore-user-config' "$codex_log" ||
  die "Codex inherited user-configured external tools"
grep -q -- 'mcp_servers={}' "$codex_log" ||
  die "Codex inherited project-configured MCP servers"
grep -q -- '--output-schema' "$codex_log" ||
  die "Codex did not receive the Invariant response schema"
grep -q 'Request kind: governance.audit' "$codex_stdin" ||
  die "Codex did not receive the audit request"
grep -q 'source:reference-' "$codex_stdin" ||
  die "governance audit did not receive the registered grounding source"
grep -q 'untrusted evidence' "$codex_stdin" ||
  die "governance audit did not preserve the source authority boundary"
status=$(cd "$governance" && "$cli" governance status harness-audit)
printf '%s\n' "$status" | grep -q '^GOVERNANCE-PHASE: adopt$' ||
  die "the submitted audit did not advance through Invariant"
ok "Codex resolves a read-only governance audit through the core CLI contract"

briefing="$fixtures/briefing"
new_repo "$briefing"
cat >>"$briefing/.invariant/config.yml" <<'EOF'
adapters:
  intent_brief: on
EOF
git -C "$briefing" add .invariant/config.yml
git -C "$briefing" commit -qm "enable intent brief"
goal='Clarify the requested behavior before implementation'
goal_digest=$(printf '%s' "$goal" | git -C "$briefing" hash-object --stdin)
(cd "$briefing" && "$cli" task begin harness-brief --goal "$goal" >/dev/null)
claude_log="$fixtures/claude.args"
claude_stdin="$fixtures/claude.stdin"
response=$(printf \
  '{"version":1,"adapter":"intent_brief","source_goal_digest":"%s","brief":"Clarify the requested behavior without changing unrelated code.","questions":[]}' \
  "$goal_digest")

preview=$(cd "$briefing" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$claude_log" FAKE_AGENT_STDIN="$claude_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" resolve harness-brief --using claude)
printf '%s\n' "$preview" | grep -q '^OPERATION: task.respond:intent_brief:task.created$' ||
  die "resolve did not infer the task's only pending action"
[ ! -e "$claude_log" ] || die "resolve preview invoked Claude Code"

applied=$(cd "$briefing" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$claude_log" FAKE_AGENT_STDIN="$claude_stdin" \
  FAKE_AGENT_RESPONSE="$response" "$agent" resolve harness-brief \
  --using claude --apply)
printf '%s\n' "$applied" | grep -q '^SESSION: claude-test-session$' ||
  die "Claude Code session attribution was not reported"
printf '%s\n' "$applied" | grep -q '^STATUS: submitted$' ||
  die "Claude Code result was not submitted"
grep -q -- '--restricted' "$claude_log" ||
  die "Claude Code was not constrained to restricted mode"
grep -q -- '--permission-mode plan' "$claude_log" ||
  die "Claude Code was not constrained to plan mode"
grep -q -- '--disallowedTools mcp__\*' "$claude_log" ||
  die "Claude Code inherited MCP tools"
grep -q -- '--json-schema' "$claude_log" ||
  die "Claude Code did not receive the Invariant response schema"
grep -q 'Request kind: task.respond' "$claude_stdin" ||
  die "Claude Code did not receive the lifecycle request"
status=$(cd "$briefing" && "$cli" task status harness-brief)
printf '%s\n' "$status" | grep -q '^STATUS: implementing$' ||
  die "the submitted intent brief did not advance through Invariant"
ok "resolve infers and submits a schema-bound lifecycle action through Claude Code"
