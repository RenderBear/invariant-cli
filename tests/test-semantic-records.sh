#!/bin/sh
# Verify the prose-first semantic index, supersession, reach, and commit attestation.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-semantic-records.XXXXXX")
assessment="$fixture-assessment.yml"
cleanup() { rm -rf "$fixture" "$assessment"; }
trap cleanup EXIT HUP INT TERM

die() { echo "not ok - $1"; exit 1; }
ok() { echo "ok - $1"; }

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/src" "$fixture/docs" "$fixture/checks"
printf 'one\n' >"$fixture/src/app.txt"
printf 'release\n' >"$fixture/src/release.txt"
cat >"$fixture/docs/architecture.md" <<'EOF'
# Architecture

## Legacy ownership

The application was once treated as externally owned. That interpretation is retained only as
superseded history.

## Application ownership

The application is maintained as ordinary repository-owned source. This interpretation follows
from the absence of external Git ownership, the repository build, and the user's adoption decision.

Assumption: ordinary tracked files represent repository ownership.

Alternative considered: retain the application as a submodule.

## Release reliance

Release construction relies on the accepted source-ownership interpretation.
EOF
cat >"$fixture/checks/ordinary-source.sh" <<'EOF'
#!/bin/sh
set -eu
test "$(git ls-files -s src/app.txt | cut -d ' ' -f 1)" = 100644
EOF
chmod +x "$fixture/checks/ordinary-source.sh"
git -C "$fixture" add -A
git -C "$fixture" commit -qm seed

out=$(cd "$fixture" && "$cli" task begin establish-meaning \
  --goal "Record repository ownership as an auditable interpretation" \
  --boundary recorded --path .invariant/SEMANTICS.yml)
worktree=$(printf '%s\n' "$out" | sed -n 's/^WORKTREE: //p')
mkdir -p "$worktree/.invariant"
cat >"$worktree/.invariant/SEMANTICS.yml" <<'EOF'
version: 1
records:
  - id: external-application-ownership
    document: architecture:docs/architecture.md#legacy-ownership
    authority: user:task:establish-meaning#goal
    status: superseded
    applies_to: [repo:src/app.txt]
  - id: repository-application-ownership
    document: architecture:docs/architecture.md#application-ownership
    authority: user:task:establish-meaning#goal
    applies_to: [repo:src/app.txt]
    revisit_on: [repo:.gitmodules, interface:source-ownership]
    verifies: [command:checks/ordinary-source.sh]
    supersedes: [external-application-ownership]
    relations:
      challenges: [semantic:external-application-ownership]
    facets:
      confidence: accepted
      vocabulary: [repository-owned source]
  - id: release-ownership-reliance
    document: architecture:docs/architecture.md#release-reliance
    authority: user:task:establish-meaning#goal
    applies_to: [repo:src/release.txt]
    revisit_on: [semantic:repository-application-ownership]
EOF
git -C "$worktree" add .invariant/SEMANTICS.yml
git -C "$worktree" commit -qm "record application ownership"

out=$(cd "$worktree" && "$cli" context reach --path src/app.txt)
printf '%s\n' "$out" | grep -q '^AFFECTED: semantic:repository-application-ownership (bounded)$' ||
  die "semantic applicability did not participate in reach"
out=$(cd "$worktree" && "$cli" context verifiers --path src/app.txt)
printf '%s\n' "$out" | grep -q '^VERIFY: semantic:repository-application-ownership command:checks/ordinary-source.sh$' ||
  die "semantic verifier projection was not selected"
out=$(cd "$worktree" && "$cli" --format json context semantics --path src/app.txt)
printf '%s\n' "$out" | grep -q '"id":"repository-application-ownership"' ||
  die "semantic context API did not return the applicable record"
printf '%s\n' "$out" | grep -q '"id":"release-ownership-reliance"' ||
  die "semantic context API did not retrieve a dependent interpretation"
printf '%s\n' "$out" | grep -q '"facets":{"confidence":"accepted","vocabulary":\["repository-owned source"\]}' ||
  die "semantic context API erased open-ended facets"
printf '%s\n' "$out" | grep -Eq '"digest":"[0-9a-f]{64}"' ||
  die "semantic context API did not bind the returned record to canonical prose"
if printf '%s\n' "$out" | grep -q 'external-application-ownership.*legacy-ownership'; then
  die "semantic context API returned a superseded record for an applicability query"
fi
ok "the API retrieves prose meaning, open facets, and verifier witnesses by causal coordinates"

goal_digest=$(printf '%s' "Record repository ownership as an auditable interpretation" |
  git -C "$fixture" hash-object --stdin)
cat >"$assessment" <<EOF
version: 1
goal_digest: $goal_digest
paths: [.invariant/SEMANTICS.yml]
interfaces: []
domains: []
boundary: {disposition: recorded}
governance: [semantic:repository-application-ownership, semantic:release-ownership-reliance]
architecture_reviews: [architecture:docs/architecture.md#application-ownership, architecture:docs/architecture.md#release-reliance]
checks: []
allow_open: true
EOF
out=$(cd "$fixture" && "$cli" task finish establish-meaning --assessment "$assessment")
printf '%s\n' "$out" | grep -q '^CHECK: passed — command:checks/ordinary-source.sh$' ||
  die "semantic record verifier did not run against the candidate"
attestation=$(git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Semantic,valueonly)')
printf '%s\n' "$attestation" |
  grep -Eq '^repository-application-ownership@[0-9a-f]{64}$' ||
  die "landing did not bind semantic identity to exact canonical prose"
(cd "$fixture" && "$cli" state validate --landing >/dev/null) ||
  die "valid semantic supersession and attestation were rejected"
ok "landing attests the indexed envelope and canonical prose without typing the argument body"

awk '
  /^## Release reliance$/ { print "The ownership interpretation now also governs packaging."; print "" }
  { print }
' "$fixture/docs/architecture.md" >"$fixture/docs/architecture.md.next"
mv "$fixture/docs/architecture.md.next" "$fixture/docs/architecture.md"
out=$(cd "$fixture" && "$cli" context reach --path docs/architecture.md)
printf '%s\n' "$out" | grep -q '^AFFECTED: semantic:repository-application-ownership (open)$' ||
  die "canonical prose change did not reopen its semantic record"
printf '%s\n' "$out" | grep -q '^AFFECTED: semantic:release-ownership-reliance (open)$' ||
  die "semantic revisit dependency did not propagate invalidation"
git -C "$fixture" restore docs/architecture.md
ok "semantic dependency invalidation propagates without treating ordinary code changes as meaning changes"

git -C "$fixture" commit --allow-empty -q -m "forge stale semantic binding" -m \
"Invariant-Unit: forged
Invariant-Scope: area.root
Invariant-Boundary: recorded
Invariant-Governance: semantic:repository-application-ownership
Invariant-Semantic: repository-application-ownership@0000000000000000000000000000000000000000000000000000000000000000"
if out=$(cd "$fixture" && "$cli" state validate --landing 2>&1); then
  die "state validation accepted a stale semantic attestation"
fi
printf '%s\n' "$out" | grep -q "stale semantic attestation" ||
  die "stale attestation failure was not explained"
ok "semantic attestations are challengeable and mechanically revalidated"

echo "4 semantic record checks passed"
