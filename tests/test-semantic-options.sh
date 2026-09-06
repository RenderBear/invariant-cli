#!/bin/sh
# Verify the task acceptance adapter and generalized discovery ontology.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-semantic-test.XXXXXX")
contract_file="$fixture-contract.yml"
review_file="$fixture-review.yml"
assessment="$fixture-assessment.yml"
cleanup() { rm -rf "$fixture" "$contract_file" "$review_file" "$assessment"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/.invariant" "$fixture/docs" "$fixture/src"
printf 'one\n' >"$fixture/src/a.txt"
cat >"$fixture/docs/architecture.md" <<'EOF'
# Architecture

## Source ownership

The source domain owns the durable value and consumers may not redefine it.

## Unrelated material

This section is not selected for the source task.
EOF
cat >"$fixture/.invariant/config.yml" <<'EOF'
version: 1
execution: auto
adapters:
  task_acceptance: true
EOF
cat >"$fixture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: source
    responsibility: Owns source behavior.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#source-ownership]
EOF
git -C "$fixture" add -A
git -C "$fixture" commit -qm seed
(cd "$fixture" && "$cli" evidence discovery capture implicit-source \
  --observation "Source recovery ownership is still implicit." \
  --evidence repo:src/a.txt --path src --domain source \
  --basis-prose "Code and architecture agree on ownership, but recovery behavior remains incomplete." \
  --apply >/dev/null)
git -C "$fixture" add .invariant/discoveries/implicit-source.yml
git -C "$fixture" commit -qm "record source discovery"

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

goal='Change the source with explicit acceptance'
goal_digest=$(printf '%s' "$goal" | git -C "$fixture" hash-object --stdin)
if out=$(cd "$fixture" && "$cli" task begin semantic-flow --goal "$goal" \
    --path src/a.txt --domain source 2>&1); then
  die "task acceptance adapter was silently skipped"
fi
printf '%s\n' "$out" | grep -q '^STATUS: awaiting-task-acceptance$' ||
  die "task acceptance did not expose its lifecycle gate"
[ "$(git -C "$fixture" branch --show-current)" = main ] ||
  die "intent expansion gate created the work branch early"
ok "task acceptance is an optional pre-implementation adapter gate"

cat >"$contract_file" <<EOF
version: 1
adapter: task_acceptance
source_goal_digest: $goal_digest
intent:
  goal: $goal
  outcomes:
    - id: O1
      prose: Source behavior changes.
  acceptance:
    - id: A1
      prose: The committed source contains the new value.
  constraints:
    - id: C1
      prose: Existing repository intent remains unchanged.
verification:
  level: targeted
  rationale: This bounded source change has focused repository evidence.
EOF
out=$(cd "$fixture" && "$cli" task begin semantic-flow --goal "$goal" \
  --path src/a.txt --domain source --acceptance-contract "$contract_file")
printf '%s\n' "$out" | grep -q '^STATUS: implementing$' ||
  die "expanded task did not enter implementation"
branch=$(printf '%s\n' "$out" | sed -n 's/^BRANCH: //p')
worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
[ -f "$fixture/.git/invariant/tasks/semantic-flow/adapters/task_acceptance/contract.yml" ] ||
  die "task acceptance contract was not stored under adapter runtime"
cat >"$worktree/docs/architecture.md" <<'EOF'
# Architecture

## Source ownership

Candidate prose must not become the premise used to review its own change.
EOF
guidance=$(cd "$fixture" && "$cli" task guidance semantic-flow)
printf '%s\n' "$guidance" | grep -q '^# Active task context$' ||
  die "compiled guidance omitted the active semantic envelope"
printf '%s\n' "$guidance" | grep -q '^Paths (current candidate): docs/architecture.md$' ||
  die "compiled guidance preserved stale initial paths instead of current candidate paths"
printf '%s\n' "$guidance" | grep -q '^# Task acceptance contract$' ||
  die "compiled guidance omitted the adapter contract"
printf '%s\n' "$guidance" | grep -q '^# Durable semantic reasoning$' ||
  die "stage guidance omitted durable semantic reasoning"
printf '%s\n' "$guidance" | grep -q '^# Repository archaeology$' ||
  die "stage guidance omitted repository archaeology"
printf '%s\n' "$guidance" | grep -q '^# Selected architecture prose$' ||
  die "compiled guidance omitted selected architecture prose"
printf '%s\n' "$guidance" | grep -q 'The source domain owns the durable value and consumers may not redefine it.' ||
  die "compiled guidance did not resolve the selected architecture section"
if printf '%s\n' "$guidance" | grep -q 'Candidate prose must not become the premise'; then
  die "compiled guidance read architecture from the candidate instead of accepted ground"
fi
printf '%s\n' "$guidance" | grep -q '^DISCOVERY-CONTEXT: implicit-source (open)$' ||
  die "compiled guidance omitted the relevant discovery"
printf '%s\n' "$guidance" | grep -q 'Source recovery ownership is still implicit.' ||
  die "compiled guidance reduced discovery reasoning to an identifier"
printf '%s\n' "$guidance" | grep -q '^# Progressive discovery$' ||
  die "stage guidance omitted progressive discovery prose"
printf '%s\n' "$guidance" | grep -q '^# Task acceptance adapter$' ||
  die "stage guidance omitted the enabled adapter"
git -C "$worktree" restore docs/architecture.md
ok "free-form brief, discovery, coordinate, and landing prose is compiled for the active stage"

printf 'two\n' >"$worktree/src/a.txt"
git -C "$worktree" add src/a.txt
git -C "$worktree" commit -qm implementation
cat >"$assessment" <<EOF
version: 1
goal_digest: $goal_digest
paths: [src/a.txt]
interfaces: []
domains: [source]
boundary:
  disposition: no-record
governance: []
architecture_reviews: [architecture:docs/architecture.md#source-ownership]
checks: []
EOF
if out=$(cd "$fixture" && "$cli" task finish semantic-flow --assessment "$assessment" 2>&1); then
  die "task acceptance review was silently skipped"
fi
candidate_tree=$(printf '%s\n' "$out" | sed -n 's/^CANDIDATE-TREE: //p')
[ -n "$candidate_tree" ] || die "task acceptance review did not identify the exact candidate tree"
[ -f "$fixture/.git/invariant/tasks/semantic-flow/adapters/task_acceptance/prepared-review.yml" ] ||
  die "candidate-bound adapter review was not prepared under adapter runtime"
[ "$(git -C "$fixture" show main:src/a.txt)" = one ] ||
  die "outcome gate advanced the target before review"

cat >"$review_file" <<EOF
version: 1
adapter: task_acceptance
source_goal_digest: $goal_digest
candidate_tree: $candidate_tree
results:
  - satisfies: A1
    disposition: satisfied
    prose: The candidate contains the committed value.
    evidence: [repo:src/a.txt]
  - satisfies: C1
    disposition: satisfied
    prose: The candidate leaves durable repository intent unchanged.
    evidence: [inspection:.invariant]
EOF
out=$(cd "$fixture" && "$cli" task finish semantic-flow --assessment "$assessment" --acceptance-review "$review_file")
printf '%s\n' "$out" | grep -q '^STATUS: completed$' ||
  die "satisfied exact-tree outcome review did not complete"
[ "$(git -C "$fixture" branch --show-current)" = main ] ||
  die "completed reviewed task did not restore main"
[ "$(cat "$fixture/src/a.txt")" = two ] || die "reviewed task was not landed"
if git -C "$fixture" show-ref --verify -q "refs/heads/$branch"; then
  die "reviewed task branch survived cleanup"
fi
ok "the bundled adapter binds proportional acceptance evidence to the exact candidate tree"

(cd "$fixture" && "$cli" config set authority human >/dev/null)
git -C "$fixture" add .invariant/config.yml
git -C "$fixture" commit -qm "require human semantic authority"
if out=$(cd "$fixture" && "$cli" evidence discovery capture missing-adr \
  --observation "No ADR describes the source boundary." \
  --searched docs/adr --path src --domain source --related task:document-source-boundary 2>&1); then
  die "human authority recorded a discovery without approval"
fi
printf '%s\n' "$out" | grep -q '^PROPOSAL: record discovery missing-adr' ||
  die "assisted discovery did not present the observation for approval"
[ ! -e "$fixture/.invariant/discoveries/missing-adr.yml" ] ||
  die "discovery proposal mutated tracked evidence"
out=$(cd "$fixture" && "$cli" evidence discovery capture missing-adr \
  --observation "No ADR describes the source boundary." \
  --searched docs/adr --path src --domain source --related task:document-source-boundary --apply)
printf '%s\n' "$out" | grep -q '^STATUS: open$' || die "discovery was not captured"
discovery="$fixture/.invariant/discoveries/missing-adr.yml"
grep -q '^basis:' "$discovery" || die "discovery basis is missing"
grep -q '^relevance:' "$discovery" || die "discovery relevance is missing"
grep -q '^disposition:' "$discovery" || die "discovery disposition is missing"
if out=$(cd "$fixture" && "$cli" evidence discovery resolve missing-adr \
    --prose "Track documentation as follow-up work." \
    --output task:document-source-boundary 2>&1); then
  die "human authority resolved a discovery without approval"
fi
printf '%s\n' "$out" | grep -q '^PROPOSAL: resolve discovery missing-adr$' ||
  die "human-authority discovery resolution did not request approval"
(cd "$fixture" && "$cli" evidence discovery resolve missing-adr \
  --prose "Track documentation as follow-up work." \
  --output task:document-source-boundary --apply >/dev/null)
(cd "$fixture" && "$cli" config set authority agent >/dev/null)
if (cd "$fixture" && "$cli" evidence discovery capture premature-auto \
    --observation "A candidate cannot grant itself agent authority." \
    --searched docs >/dev/null 2>&1); then
  die "unaccepted agent authority authorized its own discovery"
fi
git -C "$fixture" add .invariant/config.yml
git -C "$fixture" commit -qm "enable agent semantic authority"
out=$(cd "$fixture" && "$cli" evidence discovery capture automatic-finding \
  --observation "Agent authority may preserve this bounded finding." --searched docs)
printf '%s\n' "$out" | grep -q '^STATUS: open$' ||
  die "agent authority did not record an authorized discovery"
[ -f "$fixture/.invariant/discoveries/automatic-finding.yml" ] ||
  die "automatic discovery record is missing"
(cd "$fixture" && "$cli" config set authority human >/dev/null)
if (cd "$fixture" && "$cli" evidence discovery capture immediate-assistance \
    --observation "Human authority takes effect before its configuration lands." \
    --searched docs >/dev/null 2>&1); then
  die "switching back to human authority was not immediate"
fi
(cd "$fixture" && "$cli" state validate >/dev/null) ||
  die "discovery resolution to non-contract work was rejected"
ok "human-authority discoveries require approval while agent-authority discoveries can proceed"

echo "4 semantic option checks passed"
