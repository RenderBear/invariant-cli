#!/bin/sh
# Verify the human-facing lifecycle from connection through a landed change.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixtures=$(mktemp -d "${TMPDIR:-/tmp}/invariant-human-lifecycle.XXXXXX")
fake_bin="$fixtures/bin"
mkdir -p "$fake_bin"
export INVARIANT_HOME="$fixtures/invariant-home"
cleanup() { rm -rf "$fixtures"; }
trap cleanup EXIT HUP INT TERM

die() { echo "not ok - $1"; exit 1; }
ok() { echo "ok - $1"; }

cat >"$fake_bin/codex" <<'EOF'
#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli test'
  exit 0
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  if [ "${FAKE_REQUIRE_LOGIN:-0}" = 1 ] && [ ! -f "$FAKE_AUTH_FILE" ]; then
    echo 'Not logged in'
    exit 1
  fi
  echo 'Logged in using test account'
  exit 0
fi
if [ "${1:-}" = "login" ]; then
  if [ -n "${FAKE_AUTH_FILE:-}" ]; then
    touch "$FAKE_AUTH_FILE"
  fi
  echo 'Signed in'
  exit 0
fi
printf '%s\n' "$*" >>"$FAKE_AGENT_LOG"
output=
schema=false
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output=$1
  elif [ "$1" = "--output-schema" ]; then
    schema=true
  fi
  shift
done
[ -n "$output" ] || exit 3
request=$(cat)
printf '%s\n' "$request" >>"$FAKE_AGENT_STDIN"
if [ "$schema" = true ]; then
  case "$request" in
    *"Request kind: governance.audit"*)
      printf '%s\n' '{"version":1,"findings":[]}' >"$output"
      ;;
    *"Request kind: task.respond"*)
      review_id=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"review_id": "\([^"]*\)",*$/\1/p' | head -n 1)
      candidate_tree=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"candidate_tree": "\([^"]*\)",*$/\1/p' | head -n 1)
      printf '%s\n' "{\"version\":1,\"review_id\":\"$review_id\",\"candidate_tree\":\"$candidate_tree\",\"verdict\":\"accepted\",\"summary\":\"The exact candidate preserves the affected repository constraint.\",\"semantic_effect\":\"no-record\",\"authority\":\"agent:codex\",\"review_mode\":\"independent\",\"candidate_defects\":[],\"retained_discoveries\":[]}" >"$output"
      ;;
    *"Session mode: change"*)
      printf '%s\n' '{"action":"answer","message":"Hello from the persistent Invariant session."}' >"$output"
      ;;
    *)
      printf '%s\n' '{"message":"Hello from the selected Codex connection."}' >"$output"
      ;;
  esac
else
  printf '%s\n' 'changed by invariant' >> app.txt
  printf '%s\n' 'Implemented the requested fixture change.' >"$output"
fi
printf '%s\n' '{"type":"thread.started","thread_id":"codex-human-session"}'
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
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  echo '{"loggedIn":true}'
  exit 0
fi
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "login" ]; then
  exit 0
fi
exit 4
EOF
chmod +x "$fake_bin/claude"

help=$($cli --help)
printf '%s\n' "$help" | grep -q '{init,connect,ask,start,change,establish,status,settings,set,source,help}' ||
  die "primary help omitted the coherent lifecycle"
if printf '%s\n' "$help" | grep -Eq '^    (task|governance|doctor) '; then
  die "primary help exposed protocol vocabulary"
fi
printf '%s\n' "$($cli help protocol)" | grep -q 'task' ||
  die "advanced protocol help is unavailable"
ok "one primary command surface hides the low-level protocol"

connections=$(PATH="$fake_bin:$PATH" "$cli" --format json connect)
printf '%s\n' "$connections" | grep -q '"default_harness":"codex"' ||
  die "connect did not retain the default harness"
printf '%s\n' "$connections" | grep -q '"provider":"codex","installed":true,"authenticated":true,"connected":true' ||
  die "connect did not detect the Codex login"
printf '%s\n' "$connections" | grep -q '"provider":"claude","installed":true,"authenticated":true,"connected":true' ||
  die "connect did not detect the Claude login"
auth_file="$fixtures/codex-authenticated"
PATH="$fake_bin:$PATH" FAKE_REQUIRE_LOGIN=1 FAKE_AUTH_FILE="$auth_file" \
  "$cli" connect codex >/dev/null
[ -f "$auth_file" ] || die "explicit connection did not delegate native login"
switched=$(PATH="$fake_bin:$PATH" "$cli" --format json connect --default claude)
printf '%s\n' "$switched" | grep -q '"default_harness":"claude"' ||
  die "connect did not switch the machine default harness"
PATH="$fake_bin:$PATH" "$cli" connect --default codex >/dev/null
ok "connection status, default selection, and native sign-in have direct commands"

scope_repo="$fixtures/scope-repo"
mkdir -p "$scope_repo"
git -C "$scope_repo" init -qb main
git -C "$scope_repo" config user.name test
git -C "$scope_repo" config user.email test@example.com
printf 'seed\n' >"$scope_repo/app.txt"
git -C "$scope_repo" add app.txt
git -C "$scope_repo" commit -qm seed
local_auth_file="$fixtures/local-command-auth"
(cd "$scope_repo" && PATH="$fake_bin:$PATH" FAKE_REQUIRE_LOGIN=1 \
  FAKE_AUTH_FILE="$local_auth_file" "$cli" init --defaults --agent codex >/dev/null
 )
[ -e "$local_auth_file" ] || die "local init did not connect the selected coding agent"
ok "local setup connects through the selected coding agent"

repo="$fixtures/repo"
mkdir -p "$repo"
git -C "$repo" init -qb main
git -C "$repo" config user.name test
git -C "$repo" config user.email test@example.com
git -C "$repo" config commit.gpgsign false
printf 'seed\n' >"$repo/app.txt"
git -C "$repo" add app.txt
git -C "$repo" commit -qm seed

if uninitialized=$(cd "$repo" && "$cli" status 2>&1); then
  die "status inferred repository authority before initialization"
fi
printf '%s\n' "$uninitialized" | grep -q "initialize this repository" ||
  die "an uninitialized repository did not point to invariant init"
ok "managed commands require repository initialization"

initialized=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" init --defaults --agent codex)
[ "$(cat "$repo/.invariant/runtime/harness")" = codex ] ||
  die "init did not record the selected agent as a clone-local preference"
if grep -q '^agent:' "$repo/.invariant/config.yml"; then
  die "init committed the agent selection into tracked configuration"
fi
printf '%s\n' "$initialized" | grep -q '^SETUP-COMMIT: ' ||
  die "clean initialization did not create a reproducible setup commit"
[ -z "$(git -C "$repo" status --porcelain)" ] ||
  die "initialization left a clean repository dirty"

settings=$(cd "$repo" && "$cli" --format json settings)
printf '%s\n' "$settings" | grep -q '"effective_harness":"codex"' ||
  die "settings hid the selected agent"
status=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" --format json status)
printf '%s\n' "$status" | grep -q '"harness":{"preference":"codex","effective":"codex"}' ||
  die "status hid the clone-local harness preference"
printf '%s\n' "$status" | grep -q '"provider":"codex","installed":true,"authenticated":true,"connected":true' ||
  die "status hid the selected provider connection"
(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" set harness claude >/dev/null)
[ "$(cat "$repo/.invariant/runtime/harness")" = claude ] ||
  die "set harness did not update the clone-local preference"
[ -z "$(git -C "$repo" status --porcelain)" ] ||
  die "set harness dirtied the repository"
(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" set harness codex >/dev/null)
ok "initialization and harness selection stay local to the clone"

agent_log="$fixtures/agent.args"
agent_stdin="$fixtures/agent.stdin"
(cd "$repo" && "$cli" set mode change >/dev/null)
settings=$(cd "$repo" && "$cli" settings)
printf '%s\n' "$settings" | grep -q '^SESSION-MODE: change$' ||
  die "session mode was not persisted locally"
[ -z "$(git -C "$repo" status --porcelain)" ] ||
  die "session mode dirtied tracked repository state"
conversation=$(printf '%s\n' 'Follow-up question' ':new' ':sessions' ':switch 1' \
  'Return to the first context' ':exit' | (cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" start "Initial question"))
printf '%s\n' "$conversation" | grep -q '^MODE: change$' ||
  die "start did not use the local session mode"
printf '%s\n' "$conversation" | grep -q '^SESSION: 2 — active — change — no messages yet$' ||
  die "session list did not expose the new active conversation"
printf '%s\n' "$conversation" | grep -q 'Hello from the persistent Invariant session.' ||
  die "start did not render the session answer"
grep -q '^exec --sandbox read-only' "$agent_log" ||
  die "start did not create a persistent read-only provider session"
grep -q '^exec resume' "$agent_log" ||
  die "start did not resume the selected provider context"
grep -q 'sandbox_mode="read-only"' "$agent_log" ||
  die "the resumed provider turn did not restate the read-only boundary"
(cd "$repo" && "$cli" set mode ask >/dev/null)
ok "start preserves context and switches foreground sessions without tracked state"

answer=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" ask "What owns this repository?")
[ "$answer" = "Hello from the selected Codex connection." ] ||
  die "ask did not use the repository-selected agent"
grep -q -- '--sandbox read-only' "$agent_log" ||
  die "ask did not preserve its read-only boundary"
ok "ask uses the selected provider without --using"

establishment=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id fixture-establishment)
printf '%s\n' "$establishment" | grep -q '^ESTABLISH: fixture-establishment$' ||
  die "establishment hid its lifecycle identity"
printf '%s\n' "$establishment" | grep -q '^STATUS: complete$' ||
  die "establishment did not complete"
find "$repo/.invariant/audits" -type f -name '*.yml' | grep -q . ||
  die "establishment did not land its durable audit"
ok "establish runs the audit and lands its durable result"

cat >"$repo/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: lifecycle
    responsibility: Owns the managed repository lifecycle.
    authority: user:task:test#domain
EOF
cat >"$repo/.invariant/CONSTRAINTS.yml" <<'EOF'
version: 1
constraints:
  - id: invariant-state-review
    assertion: Changes below .invariant require prospective-tree review.
    authority: user:task:test#constraint
    applies_to: [lifecycle]
    surfaces: [repo:.invariant]
    material: [repo:.invariant]
    verifies: []
EOF
git -C "$repo" add .invariant/DOMAINS.yml .invariant/CONSTRAINTS.yml
git -C "$repo" commit -q -m "record Invariant state constraint" -m "Invariant-Unit: fixture-setup
Invariant-Scope: area.root
Invariant-Boundary: recorded
Invariant-Governance: domain:lifecycle
Invariant-Governance: constraint:invariant-state-review"
empty_findings="$fixtures/empty-findings.yml"
cat >"$empty_findings" <<'EOF'
version: 1
findings: []
EOF
(cd "$repo" && "$cli" governance begin resumable-establishment >/dev/null)
(cd "$repo" && "$cli" governance audit-save resumable-establishment --input "$empty_findings" >/dev/null)
deferred=$(cd "$repo" && "$cli" governance defer resumable-establishment)
printf '%s\n' "$deferred" | grep -q '^ACTION: core:candidate-review — review_semantics$' ||
  die "audit deferral bypassed the affected semantic review"
resumed=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id resumable-establishment)
printf '%s\n' "$resumed" | grep -q '^STATUS: complete$' ||
  die "establishment did not resume from deferred candidate review"
ok "audit deferral uses semantic review and resumes through the public command"

onboarded="$fixtures/onboarded"
mkdir -p "$onboarded"
git -C "$onboarded" init -qb main
git -C "$onboarded" config user.name test
git -C "$onboarded" config user.email test@example.com
git -C "$onboarded" config commit.gpgsign false
printf 'seed\n' >"$onboarded/app.txt"
git -C "$onboarded" add app.txt
git -C "$onboarded" commit -qm seed
onboarding=$(printf '%s\n' codex agent auto auto off model yes | (cd "$onboarded" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" init))
printf '%s\n' "$onboarding" | grep -q '^ESTABLISH: establish-' ||
  die "init's final yes choice did not continue into establishment"
[ -z "$(git -C "$onboarded" status --porcelain)" ] ||
  die "init establishment left repository state dirty"
ok "initialization can establish records without a user-authored prompt"

change=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" change --id fixture-change --boundary no-record \
  "Append the fixture marker to app.txt")
printf '%s\n' "$change" | grep -q '^CHANGE: fixture-change$' ||
  die "change hid its generated lifecycle identity"
printf '%s\n' "$change" | grep -q '^STATUS: complete$' ||
  die "change did not complete"
grep -q '^changed by invariant$' "$repo/app.txt" ||
  die "the managed change was not landed into the integration checkout"
[ -z "$(git -C "$repo" status --porcelain)" ] ||
  die "the landed change left repository state dirty"
grep -q -- '--sandbox workspace-write' "$agent_log" ||
  die "change did not constrain Codex to the managed write sandbox"
archive=$(ls -d "$repo"/.invariant/runtime/history/tasks/fixture-change/*/ | head -n 1)
[ -n "$archive" ] || die "change did not archive its completed receipt"
if grep -rq 'review_mode: independent' "$archive"; then
  die "a review by the authoring provider was recorded as independent"
fi
change_status=$(cd "$repo" && "$cli" status fixture-change)
printf '%s\n' "$change_status" | grep -q '^CHANGE: fixture-change$' ||
  die "status did not expose the completed change identity"
printf '%s\n' "$change_status" | grep -q '^STATUS: complete$' ||
  die "status did not expose completed change state"
if printf '%s\n' "$change_status" | grep -q '^BOUNDARY:'; then
  die "status exposed an internal boundary"
fi
ok "change owns the isolated write, verification, review, and local landing lifecycle"

(cd "$repo" && "$cli" set execution assisted >/dev/null)
before_calls=$(wc -l <"$agent_log")
if paused=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" change --id paused-change --boundary no-record \
  "Do not write before branch approval" 2>&1); then
  die "assisted change bypassed branch approval"
fi
printf '%s\n' "$paused" | grep -q '^CHANGE: paused-change$' ||
  die "paused change did not preserve its identity"
printf '%s\n' "$paused" | grep -q '^STATUS: awaiting-branch$' ||
  die "paused change did not explain its lifecycle state"
[ "$before_calls" -eq "$(wc -l <"$agent_log")" ] ||
  die "paused change invoked the provider before worktree approval"
(cd "$repo" && "$cli" task invalidate paused-change >/dev/null)
(cd "$repo" && "$cli" set execution auto >/dev/null)
ok "assisted execution pauses before any provider write"

echo "10 human lifecycle checks passed"
