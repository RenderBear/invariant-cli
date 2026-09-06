#!/bin/sh
# Verify audit evidence framing and Git-causal freshness.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-audit-test.XXXXXX")
findings="$fixture/audit-findings.yml"
cleanup() { rm -rf "$fixture"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/docs/adr" "$fixture/src/ocr" "$fixture/ui" "$fixture/.invariant/audits" "$fixture/.invariant/discoveries"
printf '# Architecture\n' >"$fixture/docs/architecture.md"
printf '# ADR\n' >"$fixture/docs/adr/0001.md"
printf 'ocr\n' >"$fixture/src/ocr/engine.txt"
printf 'ui\n' >"$fixture/ui/view.txt"
cat >"$fixture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: ocr.engine
    responsibility: Executes OCR.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#architecture]
EOF
git -C "$fixture" add -A
git -C "$fixture" commit -qm seed
ground=$(git -C "$fixture" rev-parse HEAD)
tree=$(git -C "$fixture" rev-parse 'HEAD^{tree}')

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

out=$(cd "$fixture" && "$cli" evidence audit scope --path src/ocr/engine.txt)
printf '%s\n' "$out" | grep -q '^AUDIT: scope$' || die "scope frame missing"
printf '%s\n' "$out" | grep -q "^GROUND: $ground$" || die "ground missing"
printf '%s\n' "$out" | grep -q '^TREE: ' || die "tree missing"
printf '%s\n' "$out" | grep -q '^DERIVED: area.src$' || die "derived mechanical scope missing"
printf '%s\n' "$out" | grep -q '^DOMAIN: ocr.engine$' || die "existing semantic domain missing"
printf '%s\n' "$out" | grep -q '^SOURCE: docs/architecture.md$' || die "architecture source missing"
printf '%s\n' "$out" | grep -q "^NEXT: investigate and classify findings, then save the completed audit with 'invariant evidence audit save'$" ||
  die "directed audit transition missing"
printf '%s\n' "$out" | grep -q '^routes:' && die "audit still proposes routes"
ok "scoped audit emits causal evidence without inventing semantic records"

out=$(cd "$fixture" && "$cli" evidence audit full)
printf '%s\n' "$out" | grep -q '^AUTHORITY: agent$' || die "full audit authority missing"
printf '%s\n' "$out" | grep -q '^BOUNDARY: area.src src$' || die "full audit map missing"
ok "full audit exposes agent or human authority vocabulary"

cat >"$findings" <<'EOF'
version: 1
findings:
  - id: architecture-source
    summary: OCR behavior is described by the architecture document.
    evidence: [repo:docs/architecture.md, repo:src/ocr]
    proposed: discovery
    disposition: discovery-only
EOF
out=$(cd "$fixture" && "$cli" evidence audit save ocr --mode scope --path src/ocr --input "$findings")
audit_id=$(printf '%s\n' "$out" | sed -n 's/^AUDIT: //p')
audit_path="$fixture/.invariant/audits/$audit_id.yml"
printf '%s\n' "$audit_id" | grep -Eq '^ocr-[0-9]{8}T[0-9]{6}Z$' || die "audit label and timestamp were not reflected in its id"
printf '%s\n' "$out" | grep -q "^SAVED: .invariant/audits/$audit_id.yml$" || die "timestamped audit was not saved under audits"
printf '%s\n' "$out" | grep -Eq '^CREATED-AT: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' || die "audit timestamp was not reported"
printf '%s\n' "$out" | grep -q '^NEXT: adopt every ready finding' || die "agent authority did not continue toward adoption"
grep -q '^created_at: ' "$audit_path" || die "saved audit timestamp was not stamped"
grep -q "^ground: $ground$" "$audit_path" || die "saved audit ground was not stamped"
grep -q "^tree: $tree$" "$audit_path" || die "saved audit tree was not stamped"
(cd "$fixture" && "$cli" state validate >/dev/null) || die "tracked audit schema is invalid"
git -C "$fixture" add ".invariant/audits/$audit_id.yml"
git -C "$fixture" commit -qm "record audit"
out=$(cd "$fixture" && "$cli" evidence fresh "$audit_id")
printf '%s\n' "$out" | grep -q '^FRESH:' || die "audit commit made its own evidence stale"
ok "completed audits are stamped, validated, saved, and remain non-authoritative"

(cd "$fixture" && "$cli" config set authority human >/dev/null)
git -C "$fixture" add .invariant/config.yml
git -C "$fixture" commit -qm "select human authority"
cat >"$findings" <<'EOF'
version: 1
findings: []
EOF
out=$(cd "$fixture" && "$cli" evidence audit save human-review --mode scope --path ui --input "$findings")
human_audit_id=$(printf '%s\n' "$out" | sed -n 's/^AUDIT: //p')
printf '%s\n' "$out" | grep -q '^AUTHORITY: human$' || die "saved audit omitted human authority"
printf '%s\n' "$out" | grep -q 'adopt selected findings, or defer adoption$' ||
  die "human audit did not offer clear investigation and adoption choices"
git -C "$fixture" add ".invariant/audits/$human_audit_id.yml"
git -C "$fixture" commit -qm "save human-review audit"
ok "human authority receives review choices after the audit is safely persisted"
rm -f "$findings"

mkdir -p "$fixture/captured"
printf 'captured\n' >"$fixture/captured/fact.txt"
frame=$(cd "$fixture" && "$cli" evidence audit scope --path captured)
captured_ground=$(printf '%s\n' "$frame" | sed -n 's/^GROUND: //p')
captured_tree=$(printf '%s\n' "$frame" | sed -n 's/^TREE: //p')
cat >"$fixture/.invariant/audits/captured.yml" <<EOF
version: 1
id: captured
created_at: '2026-09-05T00:00:00Z'
ground: $captured_ground
tree: $captured_tree
mode: scope
paths: [captured]
findings: []
EOF
git -C "$fixture" add captured .invariant/audits/captured.yml
git -C "$fixture" commit -qm "record exact audited snapshot"
out=$(cd "$fixture" && "$cli" evidence fresh captured)
printf '%s\n' "$out" | grep -q '^FRESH: head matches the audited tree$' || die "captured work became stale when recorded"
ok "freshness compares the exact audited tree, not a wall clock or only its ground"

printf 'changed\n' >>"$fixture/ui/view.txt"
git -C "$fixture" commit -qam "unrelated UI change"
out=$(cd "$fixture" && "$cli" evidence fresh "$audit_id")
printf '%s\n' "$out" | grep -q '^FRESH:' || die "unrelated change made audit stale"
ok "unrelated descendants preserve audit freshness"

printf 'changed\n' >>"$fixture/docs/architecture.md"
git -C "$fixture" commit -qam "change audited evidence"
if out=$(cd "$fixture" && "$cli" evidence fresh "$audit_id" 2>&1); then die "intersecting evidence change stayed fresh"; fi
printf '%s\n' "$out" | grep -q '^STALE: changed evidence docs/architecture.md$' || die "stale evidence is not identified"
ok "intersecting descendant change makes audit stale"

echo "7 audit checks passed"
