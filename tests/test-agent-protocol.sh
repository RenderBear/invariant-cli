#!/bin/sh
# Verify the agent-facing governance, schema, preparation, runner, and cache surfaces.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixtures=$(mktemp -d "${TMPDIR:-/tmp}/invariant-agent-protocol.XXXXXX")
findings=$(mktemp "${TMPDIR:-/tmp}/invariant-findings.XXXXXX")
assessment=$(mktemp "${TMPDIR:-/tmp}/invariant-assessment.XXXXXX")
cleanup() { rm -rf "$fixtures" "$findings" "$assessment"; }
trap cleanup EXIT HUP INT TERM

die() { echo "not ok - $1"; exit 1; }
ok() { echo "ok - $1"; }

new_repo() {
  destination=$1
  mkdir -p "$destination"
  git -C "$destination" init -qb main
  git -C "$destination" config user.name test
  git -C "$destination" config user.email test@example.com
  git -C "$destination" config commit.gpgsign false
}

task_help=$($cli task begin --help)
printf '%s\n' "$task_help" | grep -q 'caller-chosen ID for one managed repository change' ||
  die "task help did not explain the task ID"

governance="$fixtures/governance"
new_repo "$governance"
printf 'seed\n' >"$governance/app.txt"
mkdir -p "$governance/.invariant"
cat >"$governance/.invariant/config.yml" <<'EOF'
version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
EOF
git -C "$governance" add -A
git -C "$governance" commit -qm seed

audit_schema=$(cd "$governance" && "$cli" --format json evidence audit schema)
printf '%s\n' "$audit_schema" | grep -q '"required":\["id","summary","evidence","proposed","disposition"\]' ||
  die "audit schema did not expose required finding fields"
assessment_schema=$(cd "$governance" && "$cli" --format json task assessment schema)
printf '%s\n' "$assessment_schema" | grep -q '"allow_open"' || die "assessment schema omitted open-reach acknowledgement"
if printf '%s\n' "$assessment_schema" | grep -q '"outcome_assessment"'; then
  die "core assessment schema still owns adapter review fields"
fi
brief_schema=$(cd "$governance" && "$cli" --format json task intent-brief schema)
printf '%s\n' "$brief_schema" | grep -q '"expand_intent"\|"brief"' ||
  die "intent brief schema omitted prose-first expansion"
printf '%s\n' "$brief_schema" | grep -q '"candidate_tree"' ||
  die "intent brief schema omitted exact-tree review binding"
if printf '%s\n' "$assessment_schema" | grep -q '"output"'; then die "schema JSON duplicated its text form"; fi
projection_schema=$(cd "$governance" && "$cli" --format json governance projection schema)
printf '%s\n' "$projection_schema" | grep -q '"retained_as"' ||
  die "governance projection schema omitted retained discoveries"
ok "audit, assessment, and adapter schemas are machine-readable and compact"

out=$(cd "$governance" && "$cli" governance begin baseline-governance)
printf '%s\n' "$out" | grep -q '^GOVERNANCE-PHASE: audit$' || die "governance pass did not enter its audit phase"
branch=$(printf '%s\n' "$out" | sed -n 's/^BRANCH: //p')
governance_worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
[ "$(git -C "$governance" branch --show-current)" = main ] || die "governance pass moved the integration checkout"
[ "$(git -C "$governance_worktree" branch --show-current)" = "$branch" ] || die "governance pass did not create its managed worktree"
cat >"$findings" <<'EOF'
version: 1
findings:
  - id: record-app-boundary
    summary: The application boundary should be recorded.
    evidence: [repo:app.txt]
    proposed: domain
    disposition: adoptable
    authority: user:task:baseline-governance#finding
    records:
      - kind: domain
        value:
          id: application
          responsibility: Owns application behavior and recovery.
          authority: user:task:baseline-governance#finding
EOF
out=$(cd "$governance" && "$cli" governance audit-save baseline-governance --input "$findings")
audit_id=$(printf '%s\n' "$out" | sed -n 's/^AUDIT: //p')
printf '%s\n' "$audit_id" | grep -Eq '^audit-[0-9]{8}T[0-9]{6}Z$' || die "governance audit did not use its timestamped neutral name"
printf '%s\n' "$out" | grep -q '^GOVERNANCE-PHASE: adopt$' || die "agent authority did not advance audit to adoption"
grep -q '^  phase: adopt$' "$governance/.invariant/runtime/briefs/baseline-governance.yml" || die "governance phase was not resumable"
grep -q '^  - record-app-boundary$' "$governance/.invariant/runtime/briefs/baseline-governance.yml" || die "ready finding was not selected automatically"
out=$(cd "$governance" && "$cli" governance project baseline-governance)
printf '%s\n' "$out" | grep -q '^FINDING-COVERAGE: record-app-boundary — projected — domain:application$' ||
  die "audit-authored governance was not projected"
printf '%s\n' "$out" | grep -q '^COVERAGE: 1/1 selected findings dispositioned$' ||
  die "selected-finding coverage was not explicit"
[ -f "$governance_worktree/.invariant/DOMAINS.yml" ] ||
  die "projection did not generate the domain registry"
coverage=$(cd "$governance" && "$cli" --format json governance coverage baseline-governance)
printf '%s\n' "$coverage" | grep -q '"record-app-boundary":{' ||
  die "coverage API omitted the selected finding"
printf '%s\n' "$coverage" | grep -q '"records":\["domain:application"\]' ||
  die "coverage API did not map the finding to its generated record"
printf 'candidate\n' >>"$governance_worktree/app.txt"
git -C "$governance_worktree" add app.txt .invariant
git -C "$governance_worktree" commit -qm "record audited candidate"
prepared=$(cd "$governance" && "$cli" --format json task assessment prepare baseline-governance)
printf '%s\n' "$prepared" | grep -q '"candidate_tree"' || die "assessment preparation omitted the candidate tree"
printf '%s\n' "$prepared" | grep -q '".invariant/DOMAINS.yml"' || die "assessment preparation omitted generated governance"
printf '%s\n' "$prepared" | grep -q '".invariant/audits/' || die "assessment preparation omitted the canonical audit"
[ -f "$governance/.invariant/runtime/tasks/baseline-governance/prepared-assessment.yml" ] ||
  die "assessment preparation did not save its ignored runtime draft"
status=$(cd "$governance" && "$cli" status)
printf '%s\n' "$status" | grep -q '^TASK: baseline-governance (implementing)$' || die "top-level status omitted the active task"
ok "a governance pass keeps audit and adoption inside one resumable managed session"

deferred="$fixtures/deferred"
new_repo "$deferred"
printf 'seed\n' >"$deferred/app.txt"
mkdir -p "$deferred/.invariant"
cat >"$deferred/.invariant/config.yml" <<'EOF'
version: 1
authority: human
execution: auto
integration_branch: main
push_remote: off
EOF
git -C "$deferred" add -A
git -C "$deferred" commit -qm seed
(cd "$deferred" && "$cli" governance begin deferred >/dev/null)
out=$(cd "$deferred" && "$cli" governance audit-save deferred --input "$findings")
deferred_audit=$(printf '%s\n' "$out" | sed -n 's/^AUDIT: //p')
printf '%s\n' "$out" | grep -q '^GOVERNANCE-PHASE: decision$' || die "human authority did not retain the adoption decision"
out=$(cd "$deferred" && "$cli" governance defer deferred)
printf '%s\n' "$out" | grep -q '^GOVERNANCE-PHASE: deferred$' || die "audit deferral was not reported"
[ "$(git -C "$deferred" branch --show-current)" = main ] || die "audit-only deferral did not restore main"
git -C "$deferred" cat-file -e "main:.invariant/audits/$deferred_audit.yml" || die "deferred audit was not landed"
[ ! -f "$deferred/.invariant/runtime/briefs/deferred.yml" ] || die "deferred governance receipt was not cleaned"
status=$(cd "$deferred" && "$cli" governance status deferred)
printf '%s\n' "$status" | grep -q '^GOVERNANCE-PHASE: completed$' ||
  die "completed governance pass had no retrospective status"
printf '%s\n' "$status" | grep -q '^ADOPTION-PHASE: deferred$' ||
  die "completed governance status lost its adoption disposition"
deferred_commit=$(git -C "$deferred" rev-parse main)
grep -q 'id: record-app-boundary$' \
  "$deferred/.invariant/runtime/history/tasks/deferred/$deferred_commit/summary.yml" ||
  die "completed governance summary lost its audit findings"
ok "human authority can land a saved audit while deferring adoption"

out=$(cd "$deferred" && "$cli" governance begin governance-refresh)
printf '%s\n' "$out" | grep -q '^GOVERNANCE-PHASE: audit$' || die "a later governance pass could not begin"
out=$(cd "$deferred" && "$cli" governance audit-save governance-refresh --input "$findings")
refresh_audit=$(printf '%s\n' "$out" | sed -n 's/^AUDIT: //p')
[ "$refresh_audit" != "$deferred_audit" ] || die "a later governance pass reused an existing audit id"
(cd "$deferred" && "$cli" governance defer governance-refresh >/dev/null)
git -C "$deferred" cat-file -e "main:.invariant/audits/$deferred_audit.yml" || die "a later pass replaced its predecessor"
git -C "$deferred" cat-file -e "main:.invariant/audits/$refresh_audit.yml" || die "a later pass did not land its audit"
ok "governance passes can be rerun against the current integration state"

architecture="$fixtures/architecture"
new_repo "$architecture"
mkdir -p "$architecture/.invariant" "$architecture/docs"
cat >"$architecture/.invariant/config.yml" <<'EOF'
version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
EOF
cat >"$architecture/docs/architecture.md" <<'EOF'
# Architecture

## Application boundary

The application owns its public behavior.
EOF
cat >"$architecture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: app
    responsibility: Owns application behavior.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#application-boundary]
EOF
git -C "$architecture" add -A
git -C "$architecture" commit -qm seed
out=$(cd "$architecture" && "$cli" task begin architecture --goal "Refine the application boundary" \
  --boundary unresolved --path docs/architecture.md --domain app)
architecture_worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
printf '\nThe application also owns recovery behavior.\n' >>"$architecture_worktree/docs/architecture.md"
git -C "$architecture_worktree" commit -qam candidate
review_request=$(cd "$architecture" && "$cli" --format json task finish architecture)
printf '%s\n' "$review_request" | grep -q '"status":"ok"' ||
  die "finish did not use the successful action protocol"
printf '%s\n' "$review_request" | grep -q '"outcome":"needs_input"' ||
  die "finish did not identify the pending semantic decision"
printf '%s\n' "$review_request" | grep -q '"id":"core:candidate-review"' ||
  die "finish did not expose one candidate-bound semantic review action"
printf '%s\n' "$review_request" | grep -q '"affected_semantics":\["architecture:docs/architecture.md#application-boundary"\]' ||
  die "finish did not include every affected semantic in the review packet"
if printf '%s\n' "$review_request" | grep -q '"input_schema"'; then
  die "default finish payload repeated the action schema"
fi
printf '%s\n' "$review_request" | grep -q '"evidence_ids":\[' ||
  die "default finish payload did not use evidence references"
action=$(cd "$architecture" && "$cli" --format json task action architecture core:candidate-review)
printf '%s\n' "$action" | grep -q '"input_schema":{' ||
  die "action expansion did not retrieve the response schema"
if printf '%s\n' "$action" | grep -q '"evidence":\['; then
  die "expanded action repeated full candidate evidence"
fi
evidence=$(cd "$architecture" && "$cli" --format json task evidence architecture)
printf '%s\n' "$evidence" | grep -q '"id":"candidate:' ||
  die "evidence listing did not expose retrievable stable ids"
prepared=$(cd "$architecture" && "$cli" --format json task assessment prepare architecture)
printf '%s\n' "$prepared" | grep -q '"boundary":{"disposition":"recorded"}' ||
  die "architecture prose was not inferred as a durable boundary change"
printf '%s\n' "$prepared" | grep -q '"governance":\["architecture:docs/architecture.md#application-boundary"\]' ||
  die "registered architecture authority was not inferred as candidate governance"
printf '%s\n' "$prepared" | grep -q '"recommended_architecture_reviews":\["architecture:docs/architecture.md#application-boundary"\]' ||
  die "affected architecture review was not exposed separately"
ok "finish compiles inferred semantics into one candidate review action"

runner="$fixtures/runner"
new_repo "$runner"
mkdir -p "$runner/.invariant" "$runner/backend"
printf 'one\n' >"$runner/app.txt"
cat >"$runner/backend/verify.sh" <<'EOF'
#!/bin/sh
set -eu
primary=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
count_file=$primary/.invariant/runtime/runner-count
count=0
if [ -f "$count_file" ]; then count=$(cat "$count_file"); fi
count=$((count + 1))
printf '%s\n' "$count" >"$count_file"
printf 'NOISY-SUCCESS-OUTPUT %s\n' "$1"
EOF
chmod +x "$runner/backend/verify.sh"
cat >"$runner/.invariant/config.yml" <<'EOF'
version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
verification:
  runners:
    backend:
      command: [sh, verify.sh, '{target}']
      cwd: backend
      cache: exact-tree
      timeout: 30
EOF
git -C "$runner" add -A
git -C "$runner" commit -qm seed

out=$(cd "$runner" && "$cli" task begin cache --goal "Exercise runner caching" --boundary no-record --path app.txt)
branch=$(printf '%s\n' "$out" | sed -n 's/^BRANCH: //p')
runner_worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
goal_digest=$(printf '%s\n' "$out" | sed -n 's/^GOAL-DIGEST: //p')
printf 'two\n' >"$runner_worktree/app.txt"
git -C "$runner_worktree" commit -qam candidate
cat >"$assessment" <<EOF
version: 1
goal_digest: $goal_digest
paths: [app.txt]
interfaces: []
domains: []
boundary: {disposition: no-record}
governance: []
architecture_reviews: []
checks: [runner:backend#tests/smoke]
EOF
mkdir -p "$runner/.invariant/runtime/tasks/cache"
cp "$assessment" "$runner/.invariant/runtime/tasks/cache/prepared-assessment.yml"
out=$(cd "$runner" && "$cli" candidate verify "$branch" --assessment "$assessment")
printf '%s\n' "$out" | grep -q '^CHECK: passed — runner:backend#tests/smoke$' || die "named runner did not execute"
if printf '%s\n' "$out" | grep -q 'NOISY-SUCCESS-OUTPUT'; then die "successful verifier logs leaked into normal output"; fi
out=$(cd "$runner" && "$cli" task finish cache --check runner:backend#tests/smoke)
printf '%s\n' "$out" | grep -q '^CHECK: reused — runner:backend#tests/smoke$' || die "finish did not reuse exact-candidate verification"
printf '%s\n' "$out" | grep -q '^CHECK-CACHE: 1 reused$' || die "verification cache summary was missing"
[ "$(cat "$runner/.invariant/runtime/runner-count")" = 1 ] || die "cached verifier executed more than once"
ok "project-aware runners retain logs and reuse exact-candidate verification receipts"

echo "6 agent protocol checks passed"
