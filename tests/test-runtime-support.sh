#!/bin/sh
# Verify every transient artifact uses one ignored runtime shared across linked
# worktrees and supports explicit cleanup.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
compat="$root/bin/invariant-compat"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-runtime-test.XXXXXX")
linked="$fixture-linked"
cleanup() { rm -rf "$fixture" "$linked"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
touch "$fixture/seed"
git -C "$fixture" add seed
git -C "$fixture" commit -qm seed

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

runtime=$(cd "$fixture" && "$compat" runtime root)
fixture_real=$(CDPATH= cd -- "$fixture" && pwd -P)
[ "$runtime" = "$fixture_real/.invariant/runtime" ] || die "runtime is not under .invariant/runtime"
ok "runtime root is under the primary worktree Invariant namespace"

git -C "$fixture" worktree add -q -b linked "$linked"
linked_runtime=$(cd "$linked" && "$compat" runtime root)
[ "$linked_runtime" = "$runtime" ] || die "linked worktree resolved a private runtime"
ok "linked worktrees share runtime"

(cd "$linked" && "$compat" runtime ensure >/dev/null)
[ -f "$runtime/.gitignore" ] || die "runtime lacks its self-ignore marker"
[ -z "$(git -C "$fixture" status --porcelain -- .invariant/runtime)" ] || die "runtime pollutes Git status"
ok "runtime self-ignores before tracked Invariant state exists"

ground=$(git -C "$fixture" rev-parse HEAD)
empty_digest=$(cd "$fixture" && "$compat" brief digest | sed -n 's/^DIGEST: //p')
mkdir -p "$runtime/plans"
cat >"$runtime/plans/done.yml" <<EOF
version: 1
id: done
goal: Exercise completed-plan cleanup.
integration_target: main
integration_ground: $ground
domains: []
governing_digest: $empty_digest
units:
  - id: one
    objective: First unit.
    dependencies: []
    paths: [one]
    verifies: [test:test-one]
  - id: two
    objective: Second unit.
    dependencies: [one]
    paths: [two]
    verifies: [test:test-two]
EOF
(cd "$fixture" && "$compat" lease create watcher --scope area.root --paths seed --duration 2h >/dev/null)
printf 'landed\n' >>"$fixture/seed"
git -C "$fixture" commit -qam "land runtime fixtures

Invariant-Unit: one
Invariant-Unit: two
Invariant-Scope: area.root"
out=$(cd "$fixture" && "$compat" runtime status)
printf '%s\n' "$out" | grep -q "^RUNTIME: $runtime$" || die "status hides runtime path"
printf '%s\n' "$out" | grep -q '^PLAN: done$' || die "status omits plan"
printf '%s\n' "$out" | grep -q '^STALE: watcher — intersecting landing touched seed' || die "status omits stale lease"
printf '%s\n' "$out" | grep -q '^VERIFICATION-RECEIPTS: 0$' || die "status omits verifier cache count"
ok "runtime status distinguishes task, verification, and coordination state"

(cd "$fixture" && "$compat" lease release watcher >/dev/null)
mkdir -p "$runtime/history/tasks/finished/deadbeef" "$runtime/verifications"
printf 'version: 1\n' >"$runtime/history/tasks/finished/deadbeef/summary.yml"
printf 'status: passed\n' >"$runtime/verifications/check.yml"
printf 'passed\n' >"$runtime/verifications/check.log"
out=$(cd "$fixture" && "$compat" runtime clean)
printf '%s\n' "$out" | grep -q '^CLEANABLE: completed plan done$' || die "dry run omits completed plan"
printf '%s\n' "$out" | grep -q '^CLEANABLE: completed task finished@deadbeef$' || die "dry run omits completed task archive"
printf '%s\n' "$out" | grep -q '^CLEANABLE: 2 verification cache file(s)$' || die "dry run omits verification cache"
[ -f "$runtime/plans/done.yml" ] || die "dry-run cleanup mutated runtime"
out=$(cd "$fixture" && "$compat" runtime clean --apply)
printf '%s\n' "$out" | grep -q '^CLEANED: completed plan done$' || die "apply omits completed plan"
printf '%s\n' "$out" | grep -q '^CLEANED: completed task finished@deadbeef$' || die "apply omits completed task archive"
printf '%s\n' "$out" | grep -q '^CLEANED: 2 verification cache file(s)$' || die "apply omits verification cache"
[ ! -e "$runtime" ] || die "empty runtime remains after cleanup"
git -C "$fixture" log -1 --format=%s | grep -q '^land runtime fixtures$' || die "cleanup changed history"
ok "cleanup is dry-run first and removes only disposable or completed state"

echo "5 runtime-support checks passed"
