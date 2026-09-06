#!/bin/sh
# Verify read-only semantic authority and integration-target resolution.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-config-test.XXXXXX")
cleanup() { rm -rf "$fixture"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb trunk
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
echo x >"$fixture/f"
git -C "$fixture" add f
git -C "$fixture" commit -qm seed

default=$(cd "$fixture" && "$cli" config show)
printf '%s\n' "$default" | grep -q '^authority: agent$'
printf '%s\n' "$default" | grep -q '^execution: auto$'
printf '%s\n' "$default" | grep -q '^integration_branch: auto$'
printf '%s\n' "$default" | grep -q '^integration_branch_resolved: trunk$'
printf '%s\n' "$default" | grep -q '^source: default$'
printf '%s\n' "$default" | grep -q '^branch_source: current$'
[ ! -e "$fixture/.invariant" ]

unborn="$fixture/unborn"
git init -qb fresh "$unborn"
unborn_out=$(cd "$unborn" && "$cli" config show)
printf '%s\n' "$unborn_out" | grep -q '^integration_branch_resolved: fresh$'
printf '%s\n' "$unborn_out" | grep -q '^integration_branch_unborn: true$'

mkdir -p "$fixture/.invariant"
cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
authority: agent
execution: assisted
integration_branch: trunk
push_remote: off
EOF

explicit=$(cd "$fixture" && "$cli" config show)
printf '%s\n' "$explicit" | grep -q '^authority: agent$'
printf '%s\n' "$explicit" | grep -q '^execution: assisted$'
printf '%s\n' "$explicit" | grep -q '^integration_branch: trunk$'
printf '%s\n' "$explicit" | grep -q '^source: .invariant/config.yml$'
printf '%s\n' "$explicit" | grep -q '^integration_branch_resolved: trunk$'
printf '%s\n' "$explicit" | grep -q '^branch_source: config$'

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
EOF
omitted=$(cd "$fixture" && "$cli" config show)
printf '%s\n' "$omitted" | grep -q '^authority: agent$'
printf '%s\n' "$omitted" | grep -q '^execution: auto$'
printf '%s\n' "$omitted" | grep -q '^integration_branch: auto$'
printf '%s\n' "$omitted" | grep -q '^source: .invariant/config.yml$'
printf '%s\n' "$omitted" | grep -q '^integration_branch_resolved: trunk$'
printf '%s\n' "$omitted" | grep -q '^branch_source: current$'

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
authority: committee
EOF
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - invalid authority value was accepted"
  exit 1
fi

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
resolution: auto
EOF
if out=$(cd "$fixture" && "$cli" config show 2>&1); then
  echo "not ok - removed resolution field was accepted"
  exit 1
fi
printf '%s\n' "$out" | grep -q "unknown field 'resolution'" || {
  echo "not ok - removed resolution field was not rejected as unknown"
  exit 1
}

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
execution: deferred
EOF
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - invalid execution value was accepted"
  exit 1
fi

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
push_remote: maybe
EOF
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - invalid push_remote value was accepted"
  exit 1
fi

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
workers: subagent
EOF
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - removed workers field was accepted"
  exit 1
fi

cat >"$fixture/.invariant/config.yml" <<EOF
version: 1
integration_branch: missing
EOF
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - missing configured branch silently fell back"
  exit 1
fi

rm -f "$fixture/.invariant/config.yml"
git -C "$fixture" checkout -q --detach
if (cd "$fixture" && "$cli" config show >/dev/null 2>&1); then
  echo "not ok - detached HEAD without an explicit target was accepted"
  exit 1
fi

captured=$(cd "$fixture" && INVARIANT_INTEGRATION_TARGET=trunk "$cli" config show)
printf '%s\n' "$captured" | grep -q '^integration_branch_resolved: trunk$'
printf '%s\n' "$captured" | grep -q '^branch_source: captured$'

echo "12 configuration resolution checks passed"
