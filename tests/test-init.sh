#!/bin/sh
# Verify repository bootstrap, agent instruction installation, and interactive choices.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixtures=$(mktemp -d "${TMPDIR:-/tmp}/invariant-init-test.XXXXXX")
fake_bin="$fixtures/bin"
mkdir -p "$fake_bin"
export INVARIANT_HOME="$fixtures/invariant-home"
export INVARIANT_DEFAULT_HARNESS=codex
export INVARIANT_CODEX="$fake_bin/codex"
export INVARIANT_CLAUDE="$fake_bin/missing-claude"
cleanup() { rm -rf "$fixtures"; }
trap cleanup EXIT HUP INT TERM

cat >"$fake_bin/codex" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then
  echo 'codex-cli test'
  exit 0
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  echo 'Logged in using test account'
  exit 0
fi
exit 4
EOF
chmod +x "$fake_bin/codex"

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

init_help=$($cli init --help)
if printf '%s\n' "$init_help" | grep -Eq -- '--(no-)?establish'; then
  die "init still exposes establishment control flags"
fi
if printf '%s\n' "$init_help" | grep -q -- '--advanced'; then
  die "init still exposes a redundant advanced mode"
fi
ok "init keeps establishment as one final yes-or-no choice"

defaults="$fixtures/defaults"
new_repo "$defaults" main
printf '# Existing Codex instructions\n' >"$defaults/AGENTS.md"
printf '# Existing Claude instructions\n' >"$defaults/CLAUDE.md"
cp "$defaults/AGENTS.md" "$fixtures/AGENTS.before"
cp "$defaults/CLAUDE.md" "$fixtures/CLAUDE.before"

out=$(cd "$defaults" && "$cli" init --defaults --agent auto)
if grep -q '^agent:' "$defaults/.invariant/config.yml"; then die "default init committed a provider choice"; fi
grep -q '^integration_branch: auto$' "$defaults/.invariant/config.yml" || die "default init did not preserve automatic integration selection"
grep -q '^authority: agent$' "$defaults/.invariant/config.yml" || die "default init did not grant agent authority"
grep -q '^push_remote: off$' "$defaults/.invariant/config.yml" || die "default init enabled publication"
grep -q '^  intent_brief: off$' "$defaults/.invariant/config.yml" || die "default init omitted the adapter default"
cmp -s "$defaults/AGENTS.md" "$fixtures/AGENTS.before" || die "init modified AGENTS.md"
cmp -s "$defaults/CLAUDE.md" "$fixtures/CLAUDE.before" || die "init modified CLAUDE.md"
printf '%s\n' "$out" | grep -q "invariant establish" ||
  die "init omitted the later establishment command"
if printf '%s\n' "$out" | grep -Eq 'Decision mode|Run mode|Landing branch|Publishing|Request handling'; then
  die "--defaults entered the policy questionnaire"
fi
if printf '%s\n' "$out" | grep -q "invariant governance begin"; then
  die "init exposed the agent protocol in its recommendation"
fi
[ ! -e "$defaults/.invariant/records/domain" ] || die "init manufactured empty domains"
[ ! -e "$defaults/.invariant/records/contract" ] || die "init manufactured empty contracts"
[ ! -e "$defaults/.invariant/audits" ] || die "init ran an audit"
ok "--defaults configures the selected agent without seeding instruction files"

replacement="$fixtures/replacement"
new_repo "$replacement" main
(cd "$replacement" && "$cli" init --defaults --agent auto >/dev/null)
answers='replace
human
assisted
auto
off
model
no'
replaced=$(printf '%s\n' "$answers" | (cd "$replacement" && "$cli" init))
printf '%s\n' "$replaced" | grep -q '^! Existing configuration$' ||
  die "repeat init did not warn before replacement"
printf '%s\n' "$replaced" | grep -q 'use invariant set <key> <value>' ||
  die "repeat init did not point single-setting changes to invariant set"
grep -q '^authority: human$' "$replacement/.invariant/config.yml" || die "repeat init did not replace authority"
grep -q '^execution: assisted$' "$replacement/.invariant/config.yml" || die "repeat init did not replace execution"
[ "$(git -C "$replacement" log -1 --format=%s)" = "Reconfigure Invariant" ] ||
  die "repeat init did not commit the replacement as reconfiguration"
cp "$replacement/.invariant/config.yml" "$fixtures/replacement.before"
replacement_head=$(git -C "$replacement" rev-parse HEAD)
kept=$(printf 'keep\n' | (cd "$replacement" && "$cli" init))
cmp -s "$replacement/.invariant/config.yml" "$fixtures/replacement.before" ||
  die "keeping an existing configuration changed it"
[ "$(git -C "$replacement" rev-parse HEAD)" = "$replacement_head" ] ||
  die "keeping an existing configuration created a commit"
printf '%s\n' "$kept" | grep -q '^STATUS: unchanged$' ||
  die "keeping an existing configuration was not reported"
if printf '%s\n' "$kept" | grep -q 'GUIDED SETUP'; then
  die "repeat init asked setup questions before the user chose replacement"
fi
ok "repeat init warns first and lets the user keep or replace the complete configuration"

fallback="$fixtures/fallback"
new_repo "$fallback" main
fallback_out=$(cd "$fallback" && INVARIANT_DEFAULT_HARNESS=claude "$cli" init --defaults --agent auto)
printf '%s\n' "$fallback_out" | grep -q '^WARNING: Claude Code connection failed — .*; skipped$' ||
  die "automatic init did not warn when its preferred provider was skipped"
printf '%s\n' "$fallback_out" | grep -q '^AGENT: Codex — connected' ||
  die "automatic init did not continue to the connected provider"
git -C "$fallback" log -1 --format='%(trailers:key=Invariant-Boundary,valueonly)' |
  grep -qxF no-record || die "initialization did not establish a lifecycle coverage baseline"
ok "init warns and continues when a provider connection fails"

interactive="$fixtures/interactive"
new_repo "$interactive" trunk
git -C "$interactive" branch stable
answers='human
assisted
named
stable
on
brief
no'
printf '%s\n' "$answers" | (cd "$interactive" && "$cli" init) >/dev/null
grep -q '^authority: human$' "$interactive/.invariant/config.yml" || die "interactive authority choice was lost"
grep -q '^execution: assisted$' "$interactive/.invariant/config.yml" || die "interactive execution choice was lost"
grep -q '^integration_branch: stable$' "$interactive/.invariant/config.yml" || die "named integration branch was lost"
grep -q '^push_remote: on$' "$interactive/.invariant/config.yml" || die "interactive publication choice was lost"
grep -q '^  intent_brief: on$' "$interactive/.invariant/config.yml" || die "intent brief adapter choice was lost"
[ ! -e "$interactive/AGENTS.md" ] || die "guided init created AGENTS.md"
[ ! -e "$interactive/CLAUDE.md" ] || die "guided init created CLAUDE.md"
ok "plain init persists every repository choice without seeding instruction files"

selected="$fixtures/selected"
new_repo "$selected" main
selected_answers='human
assisted
auto
off
model
no'
printf '%s\n' "$selected_answers" | (cd "$selected" && "$cli" init --agent codex) >/dev/null
[ "$(cat "$selected/.invariant/runtime/harness")" = codex ] || die "guided init lost the selected agent"
grep -q '^authority: human$' "$selected/.invariant/config.yml" || die "--agent skipped the authority choice"
grep -q '^execution: assisted$' "$selected/.invariant/config.yml" || die "--agent skipped the execution choice"
grep -q '^push_remote: off$' "$selected/.invariant/config.yml" || die "guided init changed local-only publishing"
ok "--agent skips only agent selection while retaining the policy questionnaire"

unmanaged="$fixtures/unmanaged"
new_repo "$unmanaged" main
printf '## Invariant lifecycle\n\nManually maintained.\n' >"$unmanaged/AGENTS.md"
(cd "$unmanaged" && "$cli" init --defaults --agent auto >/dev/null)
[ -e "$unmanaged/.invariant/config.yml" ] || die "instruction content blocked initialization"
grep -q '^Manually maintained\.$' "$unmanaged/AGENTS.md" || die "init changed unmanaged instructions"
ok "init ignores agent instruction files"

dirty="$fixtures/dirty"
new_repo "$dirty" main
printf 'unfinished\n' >"$dirty/local.txt"
(cd "$dirty" && "$cli" init --defaults --agent auto >/dev/null)
if blocked=$(cd "$dirty" && "$cli" task begin before-init-commit \
  --goal "Do not start without accepted authority" 2>&1); then
  die "task creation accepted initialization absent from the integration commit"
fi
printf '%s\n' "$blocked" | grep -q "initialization is not committed" ||
  die "uncommitted initialization did not explain the blocked task"
ok "managed work starts only after initialization is committed"

echo "8 initialization checks passed"
