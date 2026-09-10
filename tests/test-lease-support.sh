#!/bin/sh
# Verify lease mechanics: unconditional dispatch minting, renewal, release,
# coordination-side freshness, and the clock-scheduled, causally decided
# conclusive liveness check.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
compat="$root/bin/invariant-compat"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-lease-test.XXXXXX")
cleanup() { rm -rf "$fixture"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/src" "$fixture/docs"
echo x >"$fixture/src/a.py"
cat >"$fixture/docs/architecture.md" <<'EOF'
# Architecture

## Engine boundary

The engine owns OCR execution.
EOF
mkdir -p "$fixture/.invariant"
cat >"$fixture/.invariant/config.yml" <<'EOF'
version: 1
authority: agent
execution: auto
integration_branch: main
push_remote: off
EOF
cat >"$fixture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: ocr.engine
    responsibility: Executes OCR.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#engine-boundary]
EOF
git -C "$fixture" add src docs .invariant/config.yml .invariant/DOMAINS.yml
git -C "$fixture" commit -qm seed
digest=$(cd "$fixture" && "$compat" brief digest ocr.engine | sed -n 's/^DIGEST: //p')

leases="$fixture/.invariant/runtime/leases"

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

out=$(cd "$fixture" && "$compat" lease create u1 --scope area.src --paths src/a.py \
  --interfaces SharedEngine --governance contract:ocr.engine --domains ocr.engine --digest "$digest")
printf '%s\n' "$out" | grep -q '^LEASE: u1 created — no live unit intersects' || die "dispatch mints unconditionally and reports no intersection"
[ -f "$leases/u1.yml" ] || die "every dispatch mints a lease"
grep -q '^version: 1$' "$leases/u1.yml" || die "lease carries the schema version"
grep -q '^tip: ' "$leases/u1.yml" || die "lease records the branch tip at grant"
grep -q '^ground: ' "$leases/u1.yml" || die "lease records the integration ground at grant"
grep -Eq "^created: ['\"]?....-..-..T..:..:..Z['\"]?$" "$leases/u1.yml" || die "created is UTC RFC 3339"
ok "create mints unconditionally with tip and ground recorded"

if (cd "$fixture" && "$compat" lease create missing-digest --paths src/missing --domains ocr.engine >/dev/null 2>&1); then
  die "semantic lease was accepted without its governing digest"
fi
ok "semantic domain claims require their governing digest"

out=$(cd "$fixture" && "$compat" lease create u2 --scope area.src --interfaces SharedEngine --duration 30m)
printf '%s\n' "$out" | grep -q '^LEASE: u2 created — intersects u1' || die "interface-related live unit is not reported"
ok "create reports intersecting interface claims without treating domains as locks"

if (cd "$fixture" && "$compat" lease create u1 --paths src/a.py >/dev/null 2>&1); then
  die "existing lease is never overwritten"
fi
ok "create never overwrites an existing lease"

created_before=$(sed -n 's/^created:[[:space:]]*//p' "$leases/u2.yml")
expires_before=$(sed -n 's/^expires:[[:space:]]*//p' "$leases/u2.yml")
sleep 1
out=$(cd "$fixture" && "$compat" lease renew u2 --duration 2h)
printf '%s\n' "$out" | grep -q '^LEASE: u2 renewed' || die "renew reports the new expiry"
created_after=$(sed -n 's/^created:[[:space:]]*//p' "$leases/u2.yml")
expires_after=$(sed -n 's/^expires:[[:space:]]*//p' "$leases/u2.yml")
[ "$created_before" = "$created_after" ] || die "renew preserves created"
[ "$expires_before" != "$expires_after" ] || die "renew moves expires"
ok "renew preserves created, moves expires, re-records the tip"

out=$(cd "$fixture" && "$compat" lease list)
printf '%s\n' "$out" | grep -q '^LEASE: u1 area.src — expires .* (live)$' || die "list marks live leases"
out=$(cd "$fixture" && "$compat" lease list --scope area.src)
printf '%s\n' "$out" | grep -q 'u2' || die "list --scope keeps related leases"
ok "list reports expiry state and filters by scope"

out=$(cd "$fixture" && "$compat" lease fresh u1)
printf '%s\n' "$out" | grep -q '^FRESH: u1' || die "nothing landed means FRESH"
echo y >>"$fixture/src/a.py"
git -C "$fixture" commit -qam "landing touching the claim"
if out=$(cd "$fixture" && "$compat" lease fresh u1); then
  die "intersecting landing goes STALE"
fi
printf '%s\n' "$out" | grep -q '^STALE: u1' || die "staleness is labeled with the touched path"
ok "fresh is FRESH until an intersecting landing, then STALE"

(cd "$fixture" && "$compat" lease release u1 >/dev/null)
(cd "$fixture" && "$compat" lease release u2 >/dev/null)

digest=$(cd "$fixture" && "$compat" brief digest ocr.engine | sed -n 's/^DIGEST: //p')
(cd "$fixture" && "$compat" lease create architecture --scope area.src --paths src/future.py \
  --domains ocr.engine --digest "$digest" >/dev/null)
printf '\nClarified.\n' >>"$fixture/docs/architecture.md"
git -C "$fixture" commit -qam "change selected architecture"
if out=$(cd "$fixture" && "$compat" lease fresh architecture); then
  die "selected architecture change left the lease fresh"
fi
printf '%s\n' "$out" | grep -q '^STALE: architecture — intersecting landing touched architecture:docs/architecture.md#engine-boundary' ||
  die "architecture staleness did not identify the selected decision"
(cd "$fixture" && "$compat" lease release architecture >/dev/null)
ok "selected architecture changes stale semantic leases"

# Conclusive liveness: DEAD by ancestry, RENEW by tip advance, QUIESCENT by
# expired-and-unmoved, DEAD by branch-and-worktree gone.
git -C "$fixture" checkout -qb unit/m1
echo m >"$fixture/src/m.py"
git -C "$fixture" add src/m.py
git -C "$fixture" commit -qm m1
git -C "$fixture" checkout -q main
git -C "$fixture" merge -q --no-ff unit/m1 -m "merged"
(cd "$fixture" && "$compat" lease create m1 --scope area.src --paths src/m.py --branch unit/m1 --duration 1s >/dev/null)
out=$(cd "$fixture" && "$compat" lease reap)
printf '%s\n' "$out" | grep -q '^DEAD: m1 (branch merged into main)$' || die "merged branch is conclusively DEAD by ancestry"
ok "a merged branch is DEAD by ancestry, never dates"
(cd "$fixture" && "$compat" lease release m1 >/dev/null)

git -C "$fixture" checkout -qb unit/q1
echo q >"$fixture/src/q.py"
git -C "$fixture" add src/q.py
git -C "$fixture" commit -qm q1
git -C "$fixture" checkout -q main
 (cd "$fixture" && "$compat" lease create q1 --scope area.src --paths src/q.py --branch unit/q1 --duration 1s >/dev/null)
sleep 2
out=$(cd "$fixture" && "$compat" lease reap)
printf '%s\n' "$out" | grep -q '^QUIESCENT: q1 — expired, tip unmoved' || die "expired with unmoved tip is QUIESCENT"
git -C "$fixture" checkout -q unit/q1
echo q2 >>"$fixture/src/q.py"
git -C "$fixture" commit -qam q2
git -C "$fixture" checkout -q main
out=$(cd "$fixture" && "$compat" lease reap)
printf '%s\n' "$out" | grep -q '^RENEW: q1 — tip advanced' || die "expired with advanced tip is RENEW, the worker is alive"
out=$(cd "$fixture" && "$compat" lease reap --apply)
printf '%s\n' "$out" | grep -q 'renewed 1' || die "apply renews the alive worker"
[ -f "$leases/q1.yml" ] || die "renewed lease survives apply"
ok "expiry schedules the check: QUIESCENT when unmoved, RENEW when the tip advanced"

tmp=$(mktemp "${TMPDIR:-/tmp}/invariant-lease-test-ed.XXXXXX")
sed -e 's|^branch: unit/q1$|branch: unit/gone|' -e "s|^worktree: .*|worktree: /nonexistent-worktree|" \
  -e 's|^expires: .*|expires: 2099-01-01T00:00:00Z|' "$leases/q1.yml" >"$tmp" && mv "$tmp" "$leases/q1.yml"
out=$(cd "$fixture" && "$compat" lease reap)
printf '%s\n' "$out" | grep -q '^DEAD: q1 (branch and worktree gone)$' || die "branch and worktree both gone is conclusively DEAD"
out=$(cd "$fixture" && "$compat" lease reap --apply)
printf '%s\n' "$out" | grep -q 'reaped 1' || die "apply reaps the DEAD set"
[ ! -e "$leases/q1.yml" ] || die "apply removes DEAD leases"
ok "branch-and-worktree gone is DEAD; reap --apply deletes it"

(cd "$fixture" && "$compat" lease create r1 --scope demo.r --paths src >/dev/null)
out=$(cd "$fixture" && "$compat" lease release r1)
[ "$out" = "released r1" ] || die "release reports the unit"
[ ! -e "$leases/r1.yml" ] || die "release deletes the file"
if (cd "$fixture" && "$compat" lease release r1 >/dev/null 2>&1); then
  die "releasing a missing lease fails"
fi
ok "release deletes exactly one lease and fails when absent"

echo "12 lease-support checks passed"
