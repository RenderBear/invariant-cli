#!/bin/sh
# Verify repository bootstrap, agent instruction installation, and interactive choices.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixtures=$(mktemp -d "${TMPDIR:-/tmp}/invariant-init-test.XXXXXX")
cleanup() { rm -rf "$fixtures"; }
trap cleanup EXIT HUP INT TERM

new_repo() {
  destination=$1
  branch=$2
  mkdir -p "$destination"
  git -C "$destination" init -qb "$branch"
  git -C "$destination" config user.name test
  git -C "$destination" config user.email test@example.com
  printf 'seed\n' >"$destination/file.txt"
  git -C "$destination" add file.txt
  git -C "$destination" commit -qm seed
}

die() { echo "not ok - $1"; exit 1; }
ok() { echo "ok - $1"; }

defaults="$fixtures/defaults"
new_repo "$defaults" main
printf '# Existing Codex instructions\n' >"$defaults/AGENTS.md"
printf '# Existing Claude instructions\n' >"$defaults/CLAUDE.md"

out=$(cd "$defaults" && "$cli" init --defaults)
grep -q '^coding_agents:$' "$defaults/.invariant/config.yml" || die "default init omitted coding agents"
grep -q '^- codex$' "$defaults/.invariant/config.yml" || die "default init omitted Codex"
grep -q '^- claude$' "$defaults/.invariant/config.yml" || die "default init omitted Claude"
grep -q '^integration_branch: auto$' "$defaults/.invariant/config.yml" || die "default init did not preserve automatic integration selection"
grep -q '^authority: agent$' "$defaults/.invariant/config.yml" || die "default init did not grant agent authority"
grep -q '^push_remote: off$' "$defaults/.invariant/config.yml" || die "default init enabled publication"
grep -q '^  intent_brief: off$' "$defaults/.invariant/config.yml" || die "default init omitted the adapter default"
grep -q '^# Existing Codex instructions$' "$defaults/AGENTS.md" || die "Codex setup replaced existing instructions"
[ "$(grep -c '^<!-- invariant:workflow:start -->$' "$defaults/AGENTS.md")" -eq 1 ] || die "Codex workflow marker is not singular"
grep -q '^## Invariant lifecycle$' "$defaults/AGENTS.md" || die "Codex workflow was not installed"
grep -q '^# Existing Claude instructions$' "$defaults/CLAUDE.md" || die "Claude setup replaced existing instructions"
grep -q '^@AGENTS.md$' "$defaults/CLAUDE.md" || die "Claude does not import the shared workflow"
printf '%s\n' "$out" | grep -q '^Recommended next step$' || die "init omitted the governance recommendation"
printf '%s\n' "$out" | grep -q '^  Run a governance pass for the repository with Invariant\.$' ||
  die "init omitted the concise governance request"
if printf '%s\n' "$out" | grep -q "invariant governance begin"; then
  die "init exposed the agent protocol in its recommendation"
fi
printf '%s\n' "$out" | grep -q "Task adapter.*Agent's own workflow" || die "default task adapter was not explained"
[ ! -e "$defaults/.invariant/DOMAINS.yml" ] || die "init manufactured empty domains"
[ ! -e "$defaults/.invariant/CONTRACTS.yml" ] || die "init manufactured empty contracts"
[ ! -e "$defaults/.invariant/audits" ] || die "init ran an audit"
ok "--defaults configures both coding agents and requests a governance pass"

interactive="$fixtures/interactive"
new_repo "$interactive" trunk
git -C "$interactive" branch stable
answers='claude
human
assisted
named
stable
on
brief'
out=$(printf '%s\n' "$answers" | (cd "$interactive" && "$cli" init))
grep -q '^coding_agents:$' "$interactive/.invariant/config.yml" || die "interactive init omitted coding agents"
grep -q '^- claude$' "$interactive/.invariant/config.yml" || die "interactive init did not select Claude"
if grep -q '^- codex$' "$interactive/.invariant/config.yml"; then die "interactive init selected Codex unexpectedly"; fi
grep -q '^authority: human$' "$interactive/.invariant/config.yml" || die "interactive authority choice was lost"
grep -q '^execution: assisted$' "$interactive/.invariant/config.yml" || die "interactive execution choice was lost"
grep -q '^integration_branch: stable$' "$interactive/.invariant/config.yml" || die "named integration branch was lost"
grep -q '^push_remote: on$' "$interactive/.invariant/config.yml" || die "interactive publication choice was lost"
grep -q '^  intent_brief: on$' "$interactive/.invariant/config.yml" || die "intent brief adapter choice was lost"
[ ! -e "$interactive/AGENTS.md" ] || die "Claude-only setup created AGENTS.md"
grep -q '^## Invariant lifecycle$' "$interactive/CLAUDE.md" || die "Claude-only workflow was not installed"
grep -q '^### Start and implement$' "$interactive/CLAUDE.md" || die "installed workflow was not structured"
[ "$(wc -l < "$interactive/CLAUDE.md")" -lt 65 ] || die "installed workflow repeated stage-specific guidance"
if grep -q '^# Human ergonomics$' "$interactive/CLAUDE.md"; then
  die "stage-specific human ergonomics were persisted in agent instructions"
fi
printf '%s\n' "$out" | grep -q '^◆ Integration branch$' || die "interactive init did not explain integration branch"
printf '%s\n' "$out" | grep -q 'Resolve the target when each task begins' || die "automatic branch behavior was not explained"
printf '%s\n' "$out" | grep -q '^◆ Task adapter$' || die "interactive init omitted the bundled adapter choice"
printf '%s\n' "$out" | grep -q '^A few things to get us started$' || die "interactive init omitted its setup heading"
[ "$(printf '%s\n' "$out" | grep -c 'enter select')" -eq 1 ] || die "interactive init repeated its input hint"
if printf '%s\n' "$out" | grep -Eq '^  [●○] [0-9]+\.'; then
  die "interactive init rendered numbered radio options"
fi
ok "interactive init explains and persists each repository choice"

ambiguous="$fixtures/ambiguous"
new_repo "$ambiguous" main
printf '## Invariant lifecycle\n\nManually maintained.\n' >"$ambiguous/AGENTS.md"
if (cd "$ambiguous" && "$cli" init --defaults >/dev/null 2>&1); then
  die "init overwrote an unmanaged workflow"
fi
[ ! -e "$ambiguous/.invariant/config.yml" ] || die "failed instruction preflight left partial config"
grep -q '^Manually maintained\.$' "$ambiguous/AGENTS.md" || die "failed preflight changed instructions"
ok "init refuses ambiguous instruction files before creating project state"

echo "3 initialization checks passed"
