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
    *"Classify one requested repository change"*)
      printf '%s\n' '{"strategy":"single","summary":"One cohesive fixture edit.","units":[]}' >"$output"
      ;;
    *"Request kind: governance.audit"*)
      if [ "${FAKE_INVALID_AUDIT:-0}" = 1 ]; then
        printf '%s\n' '{"version":1,"findings":[{"id":"invalid-projection","summary":"The application responsibility should be recorded.","evidence":["repo:app.txt"],"proposed":"domain","disposition":"adoptable","authority":"user:task:invalid-establishment#finding","records":[{"kind":"domain","value":{"id":"application","responsibility":"Owns application behavior.","authority":"user:task:invalid-establishment#finding","parent":null,"architecture":["architecture:missing.md#application"],"contracts":[]}}]}]}' >"$output"
      else
        printf '%s\n' '{"version":1,"findings":[]}' >"$output"
      fi
      ;;
    *"Request kind: governance.author"*)
      task=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"task": "\([^"]*\)",*$/\1/p' | head -n 1)
      printf '%s\n' "{\"version\":1,\"mappings\":[{\"findings\":[\"application-ownership\"],\"records\":[{\"kind\":\"domain\",\"value\":{\"id\":\"application\",\"responsibility\":\"Owns the application file.\",\"authority\":\"user:task:$task#audit\",\"parent\":null,\"architecture\":[],\"contracts\":[]}}]}]}" >"$output"
      ;;
    *"Request kind: task.respond"*)
      review_id=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"review_id": "\([^"]*\)",*$/\1/p' | head -n 1)
      candidate_tree=$(printf '%s\n' "$request" | sed -n 's/^[[:space:]]*"candidate_tree": "\([^"]*\)",*$/\1/p' | head -n 1)
      effect=no-record
      case "$request" in
        *'".invariant/records/'*) effect=recorded ;;
      esac
      printf '%s\n' "{\"version\":1,\"review_id\":\"$review_id\",\"candidate_tree\":\"$candidate_tree\",\"verdict\":\"accepted\",\"summary\":\"The exact candidate preserves the affected repository constraint.\",\"semantic_effect\":\"$effect\",\"authority\":\"agent:codex\",\"review_mode\":\"independent\",\"candidate_defects\":[],\"retained_discoveries\":[]}" >"$output"
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
printf '%s\n' "$help" | grep -q '{init,connect,ask,start,serve,project,session,change,establish,status,settings,set,source,help}' ||
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
printf '%s\n' "$conversation" | grep -q ' — active — change — New session — no messages yet$' ||
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

resume_goal="Establish or reconcile the repository's durable responsibilities, decisions, contracts, and constraints from grounded evidence."
(cd "$repo" && "$cli" governance begin establish-older --goal "$resume_goal" >/dev/null)
(cd "$repo" && "$cli" governance begin establish-current --goal "$resume_goal" >/dev/null)
resume_findings="$fixtures/resume-findings.yml"
printf 'version: 1\nfindings: []\n' >"$resume_findings"
(cd "$repo" && "$cli" governance audit-save establish-current --input "$resume_findings" >/dev/null)
resume_preview=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" establish --dry-run)
printf '%s\n' "$resume_preview" | grep -q '^ESTABLISH: establish-current$' ||
  die "bare establish did not resume the latest compatible repository-record session"
printf '%s\n' "$resume_preview" | grep -q '^STATUS: resume$' ||
  die "resumed establishment was presented as a new attempt"
resume_status=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" status)
printf '%s\n' "$resume_status" | grep -q '^STATUS: 1 unfinished change$' ||
  die "status counted equivalent establishment attempts as separate user work"
printf '%s\n' "$resume_status" | grep -q '^CHANGE: Repository records — ready to resume$' ||
  die "status exposed the establishment's internal lifecycle stage"
printf '%s\n' "$resume_status" | grep -q "^NEXT: resume saved work with 'invariant establish'$" ||
  die "status did not name the resumable task before its command"
resumed_establishment=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish)
printf '%s\n' "$resumed_establishment" | grep -q '^ESTABLISH: establish-current$' ||
  die "bare establish changed identity while resuming"
printf '%s\n' "$resumed_establishment" | grep -q '^STATUS: complete$' ||
  die "bare establish did not complete the retained repository-record session"
resume_complete_status=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" status)
printf '%s\n' "$resume_complete_status" | grep -q '^STATUS: ready$' ||
  die "completed establishment left equivalent older attempts as user-visible work"
(cd "$repo" && "$cli" task invalidate establish-older --discard >/dev/null)
ok "establishment resumes as one foreground operation without leaking task stages"

if invalid_establishment=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" FAKE_INVALID_AUDIT=1 \
  "$cli" establish --id invalid-establishment 2>&1); then
  die "establishment accepted a generated record with an absent architecture anchor"
fi
printf '%s\n' "$invalid_establishment" | grep -q '^STATUS: stopped$' ||
  die "failed establishment did not state that it stopped"
printf '%s\n' "$invalid_establishment" | grep -q "^PROBLEM: .*architecture 'missing.md' does not exist" ||
  die "failed establishment hid the concrete generated-record problem"
printf '%s\n' "$invalid_establishment" | grep -q '^SAVED: repository inspection and unfinished work$' ||
  die "failed establishment did not identify retained work"
printf '%s\n' "$invalid_establishment" | grep -q "^NEXT: retry from saved work with 'invariant establish --id invalid-establishment'$" ||
  die "failed establishment did not name the retry task and command"
retry_status=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" status)
printf '%s\n' "$retry_status" | grep -q '^CHANGE: Repository records — needs retry$' ||
  die "status hid the failed repository-record attempt"
printf '%s\n' "$retry_status" | grep -q "^PROBLEM: .*architecture 'missing.md' does not exist" ||
  die "status hid the retry reason"
printf '%s\n' "$retry_status" | grep -q "^NEXT: retry from saved work with 'invariant establish'$" ||
  die "status did not expose the public retry command"
retried_establishment=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id invalid-establishment)
printf '%s\n' "$retried_establishment" | grep -q '^STATUS: complete$' ||
  die "the advertised establishment retry did not resume and complete"
ok "failed establishment exposes and completes one situation-specific retry"

(cd "$repo" && "$cli" governance begin legacy-invalid-projection --goal "$resume_goal" >/dev/null)
(cd "$repo" && "$cli" governance audit-save legacy-invalid-projection \
  --input "$resume_findings" >/dev/null)
cat >>"$repo/.invariant/runtime/briefs/legacy-invalid-projection.yml" <<'EOF'
last_failure:
  code: invalid_adoption_projection
  message: projected repository records are invalid
EOF
legacy_retry=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id legacy-invalid-projection)
printf '%s\n' "$legacy_retry" | grep -q '^STATUS: complete$' ||
  die "retry replayed an older structurally invalid projection"
ok "retry returns older invalid generated projections to investigation"

(cd "$repo" && "$cli" set authority human >/dev/null)
(cd "$repo" && "$cli" governance begin human-establishment --goal "$resume_goal" >/dev/null)
human_findings="$fixtures/human-findings.yml"
cat >"$human_findings" <<'EOF'
version: 1
findings:
  - id: application-responsibility
    summary: The application file is the repository's stable implementation surface.
    evidence: [repo:app.txt]
    proposed: domain
    disposition: adoptable
    authority: user:task:human-establishment#decision
EOF
(cd "$repo" && "$cli" governance audit-save human-establishment --input "$human_findings" >/dev/null)
if human_decision=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  "$cli" establish --id human-establishment 2>&1); then
  die "non-interactive human authority bypassed the user's opinion"
fi
printf '%s\n' "$human_decision" | grep -q '^STATUS: needs-your-decision$' ||
  die "human authority did not receive a decision state"
printf '%s\n' "$human_decision" | grep -q '^REQUEST: choose all, none, or selected audited findings$' ||
  die "human authority did not receive an opinion-sized request"
printf '%s\n' "$human_decision" | grep -q '^PROCESS: no background worker — the proposal is preserved$' ||
  die "human decision output implied that implementation was still running"
printf '%s\n' "$human_decision" | grep -q '^NEXT: rerun invariant establish in an interactive terminal$' ||
  die "human decision output exposed a protocol continuation"
(cd "$repo" && "$cli" task invalidate human-establishment --discard >/dev/null)
(cd "$repo" && "$cli" set authority agent >/dev/null)
ok "human authority is asked only for an opinion while mechanics remain managed"

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

mkdir -p "$repo/.invariant/records/domain" "$repo/.invariant/records/constraint"
cat >"$repo/.invariant/records/domain/lifecycle.yml" <<'EOF'
version: 1
id: lifecycle
responsibility: Owns the managed repository lifecycle.
authority: user:task:test#domain
EOF
cat >"$repo/.invariant/records/constraint/invariant-state-review.yml" <<'EOF'
version: 1
id: invariant-state-review
assertion: Changes below .invariant require prospective-tree review.
authority: user:task:test#constraint
applies_to: [lifecycle]
surfaces: [repo:.invariant]
material: [repo:.invariant]
verifies: []
EOF
git -C "$repo" add .invariant/records/domain/lifecycle.yml .invariant/records/constraint/invariant-state-review.yml
fixture_setup_parent=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" commit -q -m "record Invariant state constraint" -m "Invariant-Unit: fixture-setup
Invariant-Scope: area.root
Invariant-Boundary: recorded
Invariant-Landing-Parent: $fixture_setup_parent
Invariant-Governance: domain:lifecycle
Invariant-Governance: constraint:invariant-state-review
Invariant-Review-Authority: user:task:test#review
Invariant-Review-Mode: independent
Invariant-Review-Digest: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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
printf '%s\n' "$resumed" | grep -q '^RECORDS: none recorded' ||
  die "a deferred establishment claimed to have recorded something"
ok "audit deferral uses semantic review and resumes through the public command"

authored_findings="$fixtures/authored-findings.yml"
cat >"$authored_findings" <<'EOF'
version: 1
findings:
  - id: application-ownership
    summary: The application file is the repository's stable implementation surface.
    evidence: [repo:app.txt]
    proposed: domain
    disposition: adoptable
    authority: user:task:authored-establishment#audit
EOF
(cd "$repo" && "$cli" governance begin authored-establishment --goal "Record application ownership" >/dev/null)
(cd "$repo" && "$cli" governance audit-save authored-establishment --input "$authored_findings" >/dev/null)
authored=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id authored-establishment)
printf '%s\n' "$authored" | grep -q '^STATUS: complete$' ||
  die "establish did not complete a finding that carried no record projection"
printf '%s\n' "$authored" | grep -q '^RECORDS: domain:application$' ||
  die "establish did not report the authored record"
grep -q 'Request kind: governance.author' "$agent_stdin" ||
  die "establish did not ask the agent to author the missing projection"
grep -q '^id: application$' "$repo/.invariant/records/domain/application.yml" ||
  die "the authored domain was not landed"
ok "establish authors record projections the audit left open"

broken_findings="$fixtures/broken-findings.yml"
cat >"$broken_findings" <<'EOF'
version: 1
findings:
  - id: broken-pointer
    summary: A finding whose contract names domains that do not exist.
    evidence: [repo:app.txt]
    proposed: contract
    disposition: adoptable
    authority: user:task:broken-establishment#audit
    records:
      - kind: contract
        value:
          id: broken.v1
          assertion: Missing domains exchange application data.
          authority: user:task:broken-establishment#audit
          between: [absent.one, absent.two]
          surfaces: [repo:app.txt]
          architecture: []
          material: [repo:app.txt]
          verifies: [test:app.txt]
EOF
(cd "$repo" && "$cli" governance begin broken-establishment --goal "Record a broken pointer" >/dev/null)
(cd "$repo" && "$cli" governance audit-save broken-establishment --input "$broken_findings" >/dev/null)
if broken=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id broken-establishment 2>&1); then
  die "establish landed a projection that does not resolve"
fi
printf '%s\n' "$broken" | grep -q "^PROBLEM: .*references missing domain 'absent.one'" ||
  die "establish hid why the projection was rejected"
printf '%s\n' "$broken" | grep -q "^OPTION: discard saved work with 'invariant establish --id broken-establishment --discard'$" ||
  die "establish did not offer a way out of a preserved proposal"
discarded=$(cd "$repo" && PATH="$fake_bin:$PATH" "$cli" establish --id broken-establishment --discard)
printf '%s\n' "$discarded" | grep -q '^STATUS: discarded$' ||
  die "establish --discard did not drop the preserved proposal"
if (cd "$repo" && PATH="$fake_bin:$PATH" "$cli" status) | grep -q 'needs retry'; then
  die "a discarded establishment still shows as retained work"
fi
ok "a rejected projection explains itself and can be discarded from the public command"

refresh_findings="$fixtures/refresh-findings.yml"
cat >"$refresh_findings" <<'EOF'
version: 1
findings:
  - id: lifecycle-refresh
    summary: The lifecycle domain now also owns landing.
    evidence: [repo:app.txt]
    proposed: domain
    disposition: adoptable
    authority: user:task:refresh-establishment#audit
    records:
      - kind: domain
        value:
          id: lifecycle
          responsibility: Owns the managed repository lifecycle and its landing.
          authority: user:task:refresh-establishment#audit
          parent: null
          architecture: []
          contracts: []
EOF
(cd "$repo" && "$cli" governance begin refresh-establishment --goal "Refresh the lifecycle domain" >/dev/null)
(cd "$repo" && "$cli" governance audit-save refresh-establishment --input "$refresh_findings" >/dev/null)
refreshed=$(cd "$repo" && PATH="$fake_bin:$PATH" \
  FAKE_AGENT_LOG="$agent_log" FAKE_AGENT_STDIN="$agent_stdin" \
  "$cli" establish --id refresh-establishment)
printf '%s\n' "$refreshed" | grep -q '^STATUS: complete$' ||
  die "establish could not re-record a domain that already existed"
grep -q 'and its landing' "$repo/.invariant/records/domain/lifecycle.yml" ||
  die "the refreshed domain definition was not landed"
ok "establish reconciles domains that already exist at the integration head"

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

echo "18 human lifecycle checks passed"
