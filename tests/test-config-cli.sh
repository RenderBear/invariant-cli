#!/bin/sh
# Verify explicit configuration defaults and safe tracked updates.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-config-cli-test.XXXXXX")
before="$fixture-config-before.yml"
cleanup() { rm -rf "$fixture" "$before"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
printf 'seed\n' >"$fixture/file.txt"
git -C "$fixture" add file.txt
git -C "$fixture" commit -qm seed

die() { echo "not ok - $1"; exit 1; }

defaults=$(cd "$fixture" && "$cli" config show)
printf '%s\n' "$defaults" | grep -q '^version: 1$' || die "default schema version is hidden"
printf '%s\n' "$defaults" | grep -q '^coding_agents: codex, claude$' || die "default coding agents are wrong"
printf '%s\n' "$defaults" | grep -q '^authority: agent$' || die "authority default is wrong"
printf '%s\n' "$defaults" | grep -q '^execution: auto$' || die "execution default is wrong"
printf '%s\n' "$defaults" | grep -q '^integration_branch: auto$' || die "branch setting default is wrong"
printf '%s\n' "$defaults" | grep -q '^integration_branch_resolved: main$' || die "automatic branch resolution is wrong"
printf '%s\n' "$defaults" | grep -q '^push_remote: off$' || die "remote push default is not off"
printf '%s\n' "$defaults" | grep -q '^adapter_task_contract: off$' || die "task contract adapter default is wrong"
[ ! -e "$fixture/.invariant" ] || die "show persisted implicit defaults"

created=$(cd "$fixture" && "$cli" config init)
printf '%s\n' "$created" | grep -q '^CONFIG: created .invariant/config.yml$' || die "init was not reported"
grep -q '^version: 1$' "$fixture/.invariant/config.yml" || die "init omitted the schema version"
grep -q '^coding_agents:$' "$fixture/.invariant/config.yml" || die "init omitted coding agents"
grep -q '^integration_branch: auto$' "$fixture/.invariant/config.yml" || die "init did not persist automatic branch selection"
grep -q '^push_remote: off$' "$fixture/.invariant/config.yml" || die "init did not persist safe push default"
grep -q '^  task_contract: off$' "$fixture/.invariant/config.yml" || die "init did not persist the adapter default"
if (cd "$fixture" && "$cli" config init >/dev/null 2>&1); then
  die "init overwrote an existing configuration"
fi

(cd "$fixture" && "$cli" config set execution assisted >/dev/null)
(cd "$fixture" && "$cli" config set authority human >/dev/null)
(cd "$fixture" && "$cli" config set coding_agents codex >/dev/null)
(cd "$fixture" && "$cli" config set push_remote on >/dev/null)
(cd "$fixture" && "$cli" config set adapters.task_contract on >/dev/null)
updated=$(cd "$fixture" && "$cli" config show)
printf '%s\n' "$updated" | grep -q '^execution: assisted$' || die "execution update was not resolved"
printf '%s\n' "$updated" | grep -q '^authority: human$' || die "authority update was not resolved"
printf '%s\n' "$updated" | grep -q '^coding_agents: codex$' || die "coding-agent update was not resolved"
printf '%s\n' "$updated" | grep -q '^push_remote: on$' || die "push update was not resolved"
printf '%s\n' "$updated" | grep -q '^adapter_task_contract: on$' || die "adapter update was not resolved"
grep -q '^push_remote: on$' "$fixture/.invariant/config.yml" || die "push setting was quoted"
grep -q '^  task_contract: on$' "$fixture/.invariant/config.yml" || die "adapter setting was not plain on"

cp "$fixture/.invariant/config.yml" "$before"
if (cd "$fixture" && "$cli" config set push_remote maybe >/dev/null 2>&1); then
  die "invalid push_remote update was accepted"
fi
cmp -s "$fixture/.invariant/config.yml" "$before" || die "invalid update changed the file"
if (cd "$fixture" && "$cli" config set coding_agents cursor >/dev/null 2>&1); then
  die "unsupported coding agent was accepted"
fi
cmp -s "$fixture/.invariant/config.yml" "$before" || die "invalid coding agent changed the file"
if (cd "$fixture" && "$cli" config set harnesses codex >/dev/null 2>&1); then
  die "removed harnesses key was accepted"
fi
cmp -s "$fixture/.invariant/config.yml" "$before" || die "removed harnesses key changed the file"
if (cd "$fixture" && "$cli" config set integration_branch missing >/dev/null 2>&1); then
  die "missing integration branch was accepted"
fi
cmp -s "$fixture/.invariant/config.yml" "$before" || die "invalid branch update changed the file"
if (cd "$fixture" && "$cli" config set version 2 >/dev/null 2>&1); then
  die "schema version was treated as a runtime setting"
fi

json=$(cd "$fixture" && "$cli" --format json config show)
printf '%s\n' "$json" | grep -q '"command":"config.show"' || die "JSON command identity is wrong"
printf '%s\n' "$json" | grep -q '"status":"ok"' || die "JSON configuration result failed"

echo "5 configuration CLI checks passed"
