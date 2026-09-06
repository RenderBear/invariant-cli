#!/bin/sh
# Verify work-branch-only landing, durable-boundary disposition, exact-tree
# review, checks, coordinated lease authentication, and atomic ref updates.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
compat="$root/bin/invariant-compat"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-land-test.XXXXXX")
caller="$fixture-caller"
cleanup() { rm -rf "$fixture" "$caller"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/.invariant/audits" "$fixture/docs" "$fixture/src" "$fixture/ui" "$fixture/checks"
cat >"$fixture/docs/architecture.md" <<'EOF'
# Architecture

## Source layout

Source behavior remains inside the source domain.
EOF
printf '*.pdf\n' >"$fixture/.gitignore"
printf 'one\n' >"$fixture/src/a.txt"
printf 'ui\n' >"$fixture/ui/view.txt"
cat >"$fixture/checks/verify.sh" <<'EOF'
#!/bin/sh
test "$(cat src/a.txt)" != broken
EOF
chmod +x "$fixture/checks/verify.sh"
cat >"$fixture/.invariant/config.yml" <<'EOF'
version: 1
authority: human
EOF
cat >"$fixture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: source
    responsibility: Owns source behavior.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#source-layout]
    contracts: [source.protocol.v1]
  - id: consumer
    responsibility: Consumes source behavior.
    authority: user:task:test#turn-1
EOF
cat >"$fixture/.invariant/CONTRACTS.yml" <<'EOF'
version: 1
contracts:
  - id: source.protocol.v1
    assertion: Source behavior remains consumable.
    authority: user:task:test#turn-1
    between: [source, consumer]
    surfaces: [repo:src]
    architecture: [architecture:docs/architecture.md#source-layout]
    verifies: [command:checks/verify.sh]
EOF
git -C "$fixture" add -A
git -C "$fixture" commit -qm seed

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }
start_branch() { git -C "$fixture" switch -qc "$1" main; }
finish_branch() {
  git -C "$fixture" add -A
  git -C "$fixture" commit -qm "$1"
  git -C "$fixture" switch -q main
}

printf 'direct\n' >"$fixture/ui/view.txt"
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land direct "direct mutation" --unit direct --scope area.ui \
    --paths ui/view.txt --boundary-review no-record >/dev/null 2>&1); then
  die "direct landing advanced a born integration branch"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "rejected direct landing moved target"
git -C "$fixture" checkout -q -- ui/view.txt
ok "born integration branches reject direct landing"

start_branch invariant/work/u1
printf 'two\n' >"$fixture/src/a.txt"
finish_branch "source update"
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land merge invariant/work/u1 "missing boundary review" --unit u1 \
    --scope area.src --domain source --reviewed architecture:docs/architecture.md#source-layout >/dev/null 2>&1); then
  die "merge landed without a boundary disposition"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "missing boundary review moved target"
if (cd "$fixture" && "$compat" land merge invariant/work/u1 "unreviewed" --unit u1 --scope area.src \
    --domain source --boundary-review no-record >/dev/null 2>&1); then
  die "architectural decision landed without review"
fi
out=$(cd "$fixture" && "$compat" land merge invariant/work/u1 "reviewed source" --unit u1 \
  --scope area.src --domain source --reviewed architecture:docs/architecture.md#source-layout --boundary-review no-record \
  --check command:checks/verify.sh --check command:checks/verify.sh)
[ "$(printf '%s\n' "$out" | grep -c '^CHECK: running — command:checks/verify.sh$')" -eq 1 ] ||
  die "duplicate auto-discovered and explicit checks did not run exactly once"
printf '%s\n' "$out" | grep -q '^CHECKS: 1 unique$' || die "unique check summary missing"
printf '%s\n' "$out" | grep -q '^BOUNDARY-REVIEW: no-record$' || die "no-record disposition missing"
printf '%s\n' "$out" | grep -q '^LANDED:' || die "reviewed candidate did not land"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Boundary,valueonly)' | grep -qxF no-record ||
  die "boundary disposition was not preserved in the landing commit"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Architecture,valueonly)' |
  grep -qxF architecture:docs/architecture.md#source-layout || die "architecture review attestation was not preserved"
ok "merge requires boundary disposition and applicable architecture review"

start_branch invariant/work/u2
printf 'broken\n' >"$fixture/src/a.txt"
finish_branch "broken source"
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land merge invariant/work/u2 "broken" --unit u2 --scope area.src \
    --domain source --reviewed architecture:docs/architecture.md#source-layout --boundary-review no-record >/dev/null 2>&1); then
  die "broken contract landed"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "failed verifier moved target"
[ "$(git -C "$fixture" show invariant/work/u2:src/a.txt)" = broken ] || die "failed landing lost branch work"
ok "failed verification leaves the integration ref unchanged and branch work recoverable"

start_branch invariant/work/ui
printf 'changed\n' >"$fixture/ui/view.txt"
finish_branch "simple UI"
out=$(cd "$fixture" && "$compat" land merge invariant/work/ui "simple UI" --unit ui --scope area.ui \
  --boundary-review no-record)
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "simple UI landing gained governance"
ok "simple local work remains low-governance while using a work branch"

start_branch invariant/work/migrations
mkdir -p "$fixture/migrations"
printf 'create table example(id integer);\n' >"$fixture/migrations/001.sql"
finish_branch "add migrations"
out=$(cd "$fixture" && "$compat" land merge invariant/work/migrations "add migrations" --unit migrations \
  --scope area.migrations --boundary-review no-record)
printf '%s\n' "$out" | grep -q '^TOPOLOGY-NEW: area.migrations$' || die "new topology was not reported"
ok "new mechanical topology prompts review without inventing governance"

start_branch invariant/work/audit
printf 'audited\n' >"$fixture/ui/view.txt"
frame=$(cd "$fixture" && "$compat" audit scope --paths ui)
audit_ground=$(printf '%s\n' "$frame" | sed -n 's/^GROUND: //p')
audit_tree=$(printf '%s\n' "$frame" | sed -n 's/^TREE: //p')
cat >"$fixture/.invariant/audits/ui-boundary.yml" <<EOF
version: 1
id: ui-boundary
created_at: '2026-09-05T00:00:00Z'
ground: $audit_ground
tree: $audit_tree
mode: scope
paths: [ui]
findings:
  - id: ui-result
    summary: UI behavior needs no durable governance.
    evidence: [repo:ui]
    proposed: none
    disposition: needs-authority
EOF
finish_branch "audit UI boundary"
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land merge invariant/work/audit "unresolved audit" --unit audit \
    --scope area.ui --boundary-review audit:ui-boundary >/dev/null 2>&1); then
  die "unresolved audit cleared boundary review"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "unresolved audit moved target"
git -C "$fixture" switch -q invariant/work/audit
sed 's/disposition: needs-authority/disposition: no-action/' "$fixture/.invariant/audits/ui-boundary.yml" >"$fixture/.invariant/audits/ui-boundary.tmp"
mv "$fixture/.invariant/audits/ui-boundary.tmp" "$fixture/.invariant/audits/ui-boundary.yml"
finish_branch "resolve UI audit"
out=$(cd "$fixture" && "$compat" land merge invariant/work/audit "audited UI" --unit audit \
  --scope area.ui --boundary-review audit:ui-boundary)
printf '%s\n' "$out" | grep -q '^BOUNDARY-REVIEW: audit:ui-boundary' || die "conclusive audit disposition missing"
ok "only a fresh conclusive scoped audit clears boundary review"

start_branch invariant/work/governance
cat >>"$fixture/docs/architecture.md" <<'EOF'

## Source naming

Source names remain explicit.
EOF
sed 's|architecture: \[architecture:docs/architecture.md#source-layout\]|architecture: [architecture:docs/architecture.md#source-layout, architecture:docs/architecture.md#source-naming]|' \
  "$fixture/.invariant/DOMAINS.yml" >"$fixture/.invariant/DOMAINS.tmp"
mv "$fixture/.invariant/DOMAINS.tmp" "$fixture/.invariant/DOMAINS.yml"
finish_branch "adopt naming architecture"
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land merge invariant/work/governance "unresolved adoption" --unit govern \
    --scope area.docs --domain source --reviewed architecture:docs/architecture.md#source-layout \
    --reviewed architecture:docs/architecture.md#source-naming --boundary-review recorded \
    --governance architecture:docs/architecture.md#source-naming >/dev/null 2>&1); then
  die "additive governance landed without resolved authority"
fi
if (cd "$fixture" && "$compat" land merge invariant/work/governance "wrong disposition" --unit govern \
    --scope area.docs --domain source --reviewed architecture:docs/architecture.md#source-layout \
    --reviewed architecture:docs/architecture.md#source-naming --boundary-review no-record --allow-open >/dev/null 2>&1); then
  die "governance change accepted a no-record disposition"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "unresolved governance moved target"
out=$(cd "$fixture" && "$compat" land merge invariant/work/governance "adopt naming" --unit govern \
  --scope area.docs --domain source --reviewed architecture:docs/architecture.md#source-layout \
  --reviewed architecture:docs/architecture.md#source-naming --boundary-review recorded \
  --governance architecture:docs/architecture.md#source-naming --allow-open)
printf '%s\n' "$out" | grep -Eq '^GOVERNANCE: (additive record establishment|existing accepted record changed or removed)$' || die "architecture adoption was not classified open or gated"
printf '%s\n' "$out" | grep -q '^BOUNDARY-REVIEW: recorded — architecture:docs/architecture.md#source-naming$' || die "recorded governance disposition missing"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Governance,valueonly)' |
  grep -qxF architecture:docs/architecture.md#source-naming || die "governance reference was not preserved in the landing commit"
ok "governance changes require authority and accepted record references"

start_branch invariant/work/worker
printf 'worker\n' >"$fixture/src/b.txt"
finish_branch "worker"
ground=$(git -C "$fixture" rev-parse HEAD)
source_digest=$(cd "$fixture" && "$compat" brief digest source | sed -n 's/^DIGEST: //p')
runtime=$(cd "$fixture" && "$compat" runtime ensure)
mkdir -p "$runtime/plans"
cat >"$runtime/plans/bundle.yml" <<EOF
version: 1
id: bundle
goal: Land parallel source work.
integration_target: main
integration_ground: $ground
domains: [source]
governing_digest: $source_digest
units:
  - id: worker
    objective: Add source worker output.
    dependencies: []
    paths: [src/b.txt]
    verifies: [command:checks/verify.sh]
  - id: followup
    objective: Follow up independently.
    dependencies: [worker]
    paths: [ui/followup.txt]
    verifies: [command:checks/verify.sh]
EOF
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" land merge invariant/work/worker "missing lease" --unit worker \
    --scope area.src --domain source --reviewed architecture:docs/architecture.md#source-layout \
    --reviewed architecture:docs/architecture.md#source-naming --boundary-review no-record --plan bundle >/dev/null 2>&1); then
  die "coordinated landing without lease succeeded"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "missing lease moved target"
(cd "$fixture" && "$compat" lease create worker --scope area.src --paths src/b.txt --domains source \
  --digest "$source_digest" --branch invariant/work/worker --integration-target main >/dev/null)
out=$(cd "$fixture" && "$compat" land merge invariant/work/worker "land worker" --unit worker \
  --scope area.src --domain source --reviewed architecture:docs/architecture.md#source-layout \
  --reviewed architecture:docs/architecture.md#source-naming --boundary-review no-record --plan bundle)
printf '%s\n' "$out" | grep -q '^LANDED:' || die "fresh matching lease did not land"
[ ! -e "$runtime/leases/worker.yml" ] || die "landed lease was not released"
[ -f "$runtime/plans/bundle.yml" ] || die "incomplete plan was removed"
ok "matching coordinated lease is authenticated and released"

last_attested=$(git -C "$fixture" rev-parse HEAD)
printf 'bypass\n' >"$fixture/ui/bypass.txt"
git -C "$fixture" add ui/bypass.txt
git -C "$fixture" commit -qm "plain integration commit"
unattested_tip=$(git -C "$fixture" rev-parse HEAD)
start_branch invariant/work/after-bypass
printf 'after bypass\n' >"$fixture/ui/after-bypass.txt"
finish_branch "work after bypass"
out=$(cd "$fixture" && "$compat" land merge invariant/work/after-bypass "cover bypass history" \
  --unit after-bypass --scope area.ui --boundary-review no-record)
expected_cover="$last_attested..$unattested_tip"
printf '%s\n' "$out" | grep -qxF "COVERAGE: $expected_cover" || die "landing did not report the covered first-parent suffix"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Covers,valueonly)' | grep -qxF "$expected_cover" ||
  die "range attestation was not preserved in the landing commit"
(cd "$fixture" && "$compat" state --landing >/dev/null) ||
  die "covered first-parent history did not validate"
ok "next landing append-only attests an ordinary integration commit"

start_branch invariant/work/other-worktree
printf 'from another worktree\n' >"$fixture/ui/from-caller.txt"
finish_branch "other worktree candidate"
printf 'downloaded artifact\n' >"$fixture/downloaded.pdf"
git -C "$fixture" worktree add -q -b caller "$caller" main
printf 'caller artifact\n' >"$caller/caller.tmp"
out=$(cd "$caller" && "$compat" land merge invariant/work/other-worktree "land elsewhere" \
  --target main --unit other-worktree --scope area.ui --boundary-review no-record)
printf '%s\n' "$out" | grep -q '^LANDED:' || die "non-target worktree landing failed"
[ -f "$fixture/ui/from-caller.txt" ] || die "checked-out integration worktree was not synchronized"
[ -f "$fixture/downloaded.pdf" ] || die "non-colliding integration artifact was removed"
[ -f "$caller/caller.tmp" ] || die "dirty caller artifact was removed"
ok "landing runs outside main and preserves non-colliding untracked files"

start_branch invariant/work/collision
printf 'candidate\n' >"$fixture/collision.pdf"
git -C "$fixture" add -f collision.pdf
finish_branch "colliding candidate"
printf 'local download\n' >"$fixture/collision.pdf"
old=$(git -C "$fixture" rev-parse HEAD)
if out=$(cd "$caller" && "$compat" land merge invariant/work/collision "reject collision" \
    --target main --unit collision --scope area.root --boundary-review no-record 2>&1); then
  die "landing overwrote an untracked integration file"
fi
printf '%s\n' "$out" | grep -q '^Invariant: untracked integration files collide with the candidate:' ||
  die "untracked collision lacks a precise diagnostic"
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "untracked collision moved the target"
ok "colliding untracked integration files stop before ref update"

printf 'direct local edit\n' >"$fixture/ui/direct.txt"
printf 'unstaged companion\n' >>"$fixture/ui/view.txt"
git -C "$fixture" add ui/direct.txt
old=$(git -C "$fixture" rev-parse HEAD)
if (cd "$fixture" && "$compat" direct-edit "direct local edit" --unit direct-local >/dev/null 2>&1); then
  die "direct edit inferred no-record without explicit acknowledgement"
fi
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "unacknowledged direct edit moved integration"
out=$(cd "$fixture" && "$compat" direct-edit "direct local edit" --unit direct-local --no-record \
  --check command:checks/verify.sh)
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "direct edit did not independently confirm local reach"
printf '%s\n' "$out" | grep -q '^LANDED:' || die "explicit local direct edit did not land"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Boundary,valueonly)' | grep -qxF no-record ||
  die "direct edit did not preserve its explicit disposition"
git -C "$fixture" log -1 --format='%(trailers:key=Invariant-Scope,valueonly)' | grep -qxF area.ui ||
  die "direct edit did not derive its path scope"
git -C "$fixture" diff --quiet -- ui/view.txt && die "direct edit discarded an unstaged companion change"
ok "direct-edit helper requires explicit no-record and preserves unstaged work"

printf 'direct semantic edit\n' >"$fixture/src/a.txt"
git -C "$fixture" add src/a.txt
old=$(git -C "$fixture" rev-parse HEAD)
if out=$(cd "$fixture" && "$compat" direct-edit "direct semantic edit" --unit direct-semantic --no-record 2>&1); then
  die "direct edit accepted bounded semantic reach"
fi
printf '%s\n' "$out" | grep -q '^Invariant: direct edit has bounded reach; use normal work-branch landing$' ||
  die "bounded direct edit lacks a recovery instruction"
[ "$(git -C "$fixture" rev-parse HEAD)" = "$old" ] || die "bounded direct edit moved integration"
git -C "$fixture" diff --cached --quiet -- src/a.txt && die "rejected direct edit lost staged work"
git -C "$fixture" restore --staged --worktree src/a.txt
ok "direct-edit helper defers governed work to normal landing"

unborn="$fixture/unborn"
mkdir -p "$unborn"
git -C "$unborn" init -qb main
git -C "$unborn" config user.name test
git -C "$unborn" config user.email test@example.com
git -C "$unborn" config commit.gpgsign false
printf '# New repository\n' >"$unborn/README.md"
out=$(cd "$unborn" && "$compat" land direct "initial commit" --unit initial --scope area.root \
  --paths README.md --boundary-review no-record)
printf '%s\n' "$out" | grep -q '^LANDED:' || die "unborn direct landing failed"
ok "direct landing remains available only for an unborn integration branch"

echo "14 landing policy checks passed"
