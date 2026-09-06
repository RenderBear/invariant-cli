#!/bin/sh
# Verify parallel-plan validation and status derivation.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
compat="$root/bin/invariant-compat"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-plan-test.XXXXXX")
cleanup() { rm -rf "$fixture"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
touch "$fixture/seed"
git -C "$fixture" add seed
git -C "$fixture" commit -qm seed
ground=$(git -C "$fixture" rev-parse HEAD)
empty_digest=$(cd "$fixture" && "$compat" brief digest | sed -n 's/^DIGEST: //p')

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

out=$(cd "$fixture" && "$compat" workboard-status)
printf '%s\n' "$out" | grep -q '^no plans$' || die "empty runtime does not report no plans"
ok "empty plan store reports cleanly"

runtime="$fixture/.invariant/runtime"
mkdir -p "$runtime/plans" "$runtime/leases"
cat >"$runtime/plans/demo.yml" <<EOF
version: 1
id: demo
goal: Establish and consume a boundary.
integration_target: main
integration_ground: $ground
domains: []
governing_digest: $empty_digest
units:
  - id: protocol
    objective: Establish the protocol.
    dependencies: []
    paths: [.invariant/CONTRACTS.yml]
    governance: [contract:demo.boundary]
    provides: [contract:demo.boundary]
    verifies: [command:checks/protocol]
  - id: api
    objective: Consume the protocol.
    dependencies: [protocol]
    paths: [services/api]
    relies_on: [contract:demo.boundary]
    verifies: [command:checks/api]
  - id: web
    objective: Update an independent client.
    dependencies: [protocol]
    paths: [apps/web]
    relies_on: [contract:demo.boundary]
    verifies: [command:checks/web]
EOF

out=$(cd "$fixture" && "$compat" workboard validate demo)
printf '%s\n' "$out" | grep -q '^PLAN: valid' || die "valid plan failed"
ok "DAG, verification, reliance order, and disjoint claims validate"

cp "$runtime/plans/demo.yml" "$runtime/plans/demo.good"
sed 's/^governing_digest:.*/governing_digest: stale/' "$runtime/plans/demo.good" >"$runtime/plans/demo.yml"
if (cd "$fixture" && "$compat" workboard validate demo >/dev/null 2>&1); then die "stale governing digest was accepted"; fi
mv "$runtime/plans/demo.good" "$runtime/plans/demo.yml"
ok "plan lifetime is guarded by the selected domain-governance digest"

cat >"$runtime/plans/bad.yml" <<EOF
version: 1
id: bad
goal: Invalid parallel overlap.
integration_target: main
integration_ground: $ground
domains: []
governing_digest: $empty_digest
units:
  - id: one
    objective: First.
    dependencies: []
    paths: [shared]
    governance: [architecture:docs/shared.md#decision]
    verifies: [test:one]
  - id: two
    objective: Second.
    dependencies: []
    paths: [other]
    governance: [architecture:docs/shared.md#decision]
    verifies: [test:two]
EOF
if (cd "$fixture" && "$compat" workboard validate bad >/dev/null 2>&1); then die "unordered governance overlap was accepted"; fi
ok "unordered governance claims collide even when paths differ"

cat >"$runtime/plans/bad.yml" <<EOF
version: 1
id: bad
goal: Invalid missing dependency.
integration_target: main
integration_ground: $ground
domains: []
governing_digest: $empty_digest
units:
  - id: setter
    objective: Set contract.
    dependencies: []
    governance: [contract:x]
    provides: [contract:x]
    verifies: [test:setter]
  - id: consumer
    objective: Consume contract.
    dependencies: []
    paths: [consumer]
    relies_on: [contract:x]
    verifies: [test:consumer]
EOF
if (cd "$fixture" && "$compat" workboard validate bad >/dev/null 2>&1); then die "unordered provider and consumer were accepted"; fi
ok "provider-before-consumer order is mechanical"
rm -f "$runtime/plans/bad.yml"

out=$(cd "$fixture" && "$compat" workboard-status demo)
printf '%s\n' "$out" | grep -Eq '^protocol +dispatchable' || die "root unit is not dispatchable"
printf '%s\n' "$out" | grep -Eq '^api +waiting' || die "consumer is not waiting"
ok "unit state derives from dependencies"

git -C "$fixture" commit --allow-empty -qm "land protocol

Invariant-Unit: protocol
Invariant-Scope: area.root"
out=$(cd "$fixture" && "$compat" workboard-status demo)
printf '%s\n' "$out" | grep -Eq '^protocol +landed' || die "trailer did not derive landed state"
printf '%s\n' "$out" | grep -Eq '^api +dispatchable' || die "dependency landing did not unlock consumer"
ok "first-parent trailers unlock dependents"

cat >"$runtime/leases/api.yml" <<'EOF'
version: 1
unit: api
EOF
out=$(cd "$fixture" && "$compat" workboard-status demo --pinned)
printf '%s\n' "$out" | grep -q '^PINNED: protocol (landed)$' || die "landed unit is not pinned"
printf '%s\n' "$out" | grep -q '^PINNED: api (leased)$' || die "leased unit is not pinned"
ok "pinned set is landed plus leased"

msg=$(cd "$fixture" && "$compat" brief message "land clients" --unit api --unit web \
  --scope area.services --scope area.apps --plan demo)
printf '%s\n' "$msg" | grep -q '^Invariant-Plan: demo$' || die "message omits plan trailer"
printf '%s\n' "$msg" | grep -q '^Invariant-Unit: web$' || die "message omits bundled unit"
ok "one convergence message can contain several bundled units"

echo "8 plan checks passed"
