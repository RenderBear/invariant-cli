#!/bin/sh
# Verify the intent brief hooks and generalized discovery ontology.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-semantic-test.XXXXXX")
unborn=$(mktemp -d "${TMPDIR:-/tmp}/invariant-unborn-hook.XXXXXX")
brief_file="$fixture-brief.yml"
review_file="$fixture-review.yml"
semantic_review="$fixture-semantic-review.yml"
cleanup() { rm -rf "$fixture" "$unborn" "$brief_file" "$review_file" "$semantic_review"; }
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
  intent_brief: on
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
out=$(cd "$fixture" && "$cli" task begin semantic-flow --goal "$goal" \
    --path src/a.txt --domain source)
printf '%s\n' "$out" | grep -q '^STATUS: briefing$' ||
  die "intent expansion did not expose its action"
printf '%s\n' "$out" | grep -q '^ACTION: intent_brief:task.created — expand_intent$' ||
  die "intent expansion action was not structured"
[ "$(git -C "$fixture" branch --show-current)" = main ] ||
  die "task creation moved the integration checkout"
branch=$(printf '%s\n' "$out" | sed -n 's/^BRANCH: //p')
worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
[ -d "$worktree" ] || die "single begin did not create the isolated worktree"
ok "one begin creates the task and exposes intent expansion as data"

cat >"$brief_file" <<EOF
version: 1
adapter: intent_brief
source_goal_digest: $goal_digest
brief: >-
  Change the committed source value while preserving existing repository governance.
questions:
  - id: desired-value
    prompt: What should the new value be?
    answer: ''
EOF
out=$(cd "$fixture" && "$cli" task respond semantic-flow intent_brief:task.created \
  --input "$brief_file")
printf '%s\n' "$out" | grep -q '^STATUS: briefing$' ||
  die "a material unanswered question did not retain briefing"
printf '%s\n' "$out" | grep -q '^ACTION: intent_brief:task.created — answer_questions$' ||
  die "the interview did not return the material question"
cat >"$brief_file" <<EOF
version: 1
adapter: intent_brief
source_goal_digest: $goal_digest
brief: >-
  Change the committed source value to two while preserving existing repository governance.
questions:
  - id: desired-value
    prompt: What should the new value be?
    answer: Use the literal value two.
EOF
out=$(cd "$fixture" && "$cli" task respond semantic-flow intent_brief:task.created \
  --input "$brief_file")
printf '%s\n' "$out" | grep -q '^STATUS: implementing$' ||
  die "answered intent brief did not enter implementation"
[ -f "$fixture/.git/invariant/tasks/semantic-flow/adapters/intent_brief/brief.yml" ] ||
  die "intent brief was not stored under adapter runtime"
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
printf '%s\n' "$guidance" | grep -q '^# Intent brief$' ||
  die "compiled guidance omitted the intent brief"
if printf '%s\n' "$guidance" | grep -q '^# Repository archaeology$'; then
  die "default guidance returned the full generic handbook"
fi
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
printf '%s\n' "$guidance" | grep -q 'Do not create requirement taxonomies' ||
  die "stage guidance omitted the enabled adapter"
full_guidance=$(cd "$fixture" && "$cli" task guidance semantic-flow --full)
printf '%s\n' "$full_guidance" | grep -q '^# Repository archaeology$' ||
  die "full guidance did not expose the detailed handbook"
git -C "$worktree" restore docs/architecture.md
ok "guidance compiles accepted context and keeps the long handbook lazy"

printf 'two\n' >"$worktree/src/a.txt"
git -C "$worktree" add src/a.txt
git -C "$worktree" commit -qm implementation
out=$(cd "$fixture" && "$cli" task finish semantic-flow)
candidate_tree=$(printf '%s\n' "$out" | sed -n 's/^CANDIDATE-TREE: //p')
[ -n "$candidate_tree" ] || die "finish did not identify the exact candidate tree"
printf '%s\n' "$out" | grep -q '^ACTION: intent_brief:candidate.evidenced — review_intent$' ||
  die "intent review hook was not exposed"
printf '%s\n' "$out" | grep -q '^ACTION: core:candidate-review — review_semantics$' ||
  die "affected semantic prose was not compiled into the final review"
[ "$(git -C "$fixture" show main:src/a.txt)" = one ] ||
  die "review actions advanced the target"

brief_digest=$(shasum -a 256 "$fixture/.git/invariant/tasks/semantic-flow/adapters/intent_brief/brief.yml" | awk '{print $1}')
cat >"$review_file" <<EOF
version: 1
adapter: intent_brief
source_goal_digest: $goal_digest
brief_digest: $brief_digest
candidate_tree: $candidate_tree
verdict: accepted
summary: The exact candidate implements the whole intent brief.
exceptions: []
EOF
out=$(cd "$fixture" && "$cli" task respond semantic-flow intent_brief:candidate.evidenced \
  --input "$review_file")
printf '%s\n' "$out" | grep -q '^STATUS: awaiting-review$' ||
  die "resolving intent review discarded the core semantic action"
cat >"$semantic_review" <<EOF
version: 1
review_id: $(sed -n 's/^review_id: //p' "$fixture/.git/invariant/tasks/semantic-flow/review-packet.yml")
candidate_tree: $candidate_tree
verdict: accepted
summary: The bounded source change preserves the accepted ownership decision.
semantic_effect: no-record
authority: agent:semantic-flow
exceptions: []
EOF
out=$(cd "$fixture" && "$cli" task respond semantic-flow core:candidate-review \
  --input "$semantic_review")
printf '%s\n' "$out" | grep -q '^STATUS: completed$' ||
  die "resolved exact-tree reviews did not complete"
[ "$(git -C "$fixture" branch --show-current)" = main ] ||
  die "completed reviewed task did not restore main"
[ "$(cat "$fixture/src/a.txt")" = two ] || die "reviewed task was not landed"
if git -C "$fixture" show-ref --verify -q "refs/heads/$branch"; then
  die "reviewed task branch survived cleanup"
fi
landed=$(git -C "$fixture" rev-parse main)
[ -f "$fixture/.git/invariant/history/tasks/semantic-flow/$landed/receipt.yml" ] ||
  die "completion discarded the argument trail"
[ -d "$fixture/.git/invariant/history/tasks/semantic-flow/$landed/evidence" ] ||
  die "completion discarded exact-tree evidence"
ok "whole-intent and semantic reviews bind archived evidence to the exact candidate"

git -C "$unborn" init -qb main
git -C "$unborn" config user.name test
git -C "$unborn" config user.email test@example.com
mkdir -p "$unborn/.invariant"
cat >"$unborn/.invariant/config.yml" <<'EOF'
version: 1
execution: auto
adapters:
  intent_brief: on
EOF
unborn_goal='Establish the first repository tree'
unborn_digest=$(printf '%s' "$unborn_goal" | git -C "$unborn" hash-object --stdin)
out=$(cd "$unborn" && "$cli" task begin unborn-intent --goal "$unborn_goal")
printf '%s\n' "$out" | grep -q '^STATUS: briefing$' ||
  die "an unborn repository bypassed its task-created hook"
out=$(cd "$unborn" && "$cli" task status unborn-intent)
printf '%s\n' "$out" | grep -q '^ACTION: intent_brief:task.created — expand_intent$' ||
  die "task status did not expose the pending hook action"
cat >"$brief_file" <<EOF
version: 1
adapter: intent_brief
source_goal_digest: $unborn_digest
brief: Establish the requested first repository tree without publishing it.
questions: []
EOF
out=$(cd "$unborn" && "$cli" task respond unborn-intent intent_brief:task.created \
  --input "$brief_file")
printf '%s\n' "$out" | grep -q '^STATUS: implementing-unborn$' ||
  die "resolved unborn intent did not return to direct implementation"
ok "task-created hooks gate both born and unborn repository lifecycles"

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

echo "5 semantic option checks passed"
