#!/bin/sh
# Verify semantic-domain briefing, reach, digests, and trailer containment.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
compat="$root/bin/invariant-compat"
cli="$root/bin/invariant"
fixture=$(mktemp -d "${TMPDIR:-/tmp}/invariant-brief-test.XXXXXX")
cleanup() { rm -rf "$fixture"; }
trap cleanup EXIT HUP INT TERM

git -C "$fixture" init -qb main
git -C "$fixture" config user.name test
git -C "$fixture" config user.email test@example.com
git -C "$fixture" config commit.gpgsign false
mkdir -p "$fixture/.invariant/audits" "$fixture/.invariant/discoveries" "$fixture/.hidden" \
  "$fixture/Upper Dir" "$fixture/packages/Fancy App" "$fixture/docs" "$fixture/src/ocr" \
  "$fixture/ui" "$fixture/schemas" "$fixture/checks"
cat >"$fixture/docs/architecture.md" <<'EOF'
# OCR architecture

## Provider isolation

Provider details remain inside engines.
EOF
cat >"$fixture/README.md" <<'EOF'
# Example

## Submit and observe a job

Submit work and observe its events.

## Local setup

Run the local service.
EOF
printf '{}\n' >"$fixture/schemas/ocr.json"
printf 'ocr\n' >"$fixture/src/ocr/engine.txt"
printf 'ui\n' >"$fixture/ui/view.txt"
printf 'hidden\n' >"$fixture/.hidden/existing.txt"
printf 'upper\n' >"$fixture/Upper Dir/existing.txt"
printf '{}\n' >"$fixture/packages/Fancy App/package.json"
printf '{}\n' >"$fixture/package.json"
cat >"$fixture/checks/verify.sh" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$fixture/checks/verify.sh"
cat >"$fixture/.invariant/config.yml" <<'EOF'
version: 1
authority: human
EOF
cat >"$fixture/.invariant/DOMAINS.yml" <<'EOF'
version: 1
domains:
  - id: ocr
    responsibility: Owns OCR capabilities.
    authority: user:task:test#turn-1
    architecture: [architecture:docs/architecture.md#provider-isolation]
    contracts: [ocr.protocol.v1]
  - id: ocr.orchestrator
    responsibility: Selects engines.
    authority: user:task:test#turn-1
    parent: ocr
  - id: ocr.external
    responsibility: Runs an external OCR provider.
    authority: user:task:test#turn-1
    parent: ocr
EOF
cat >"$fixture/.invariant/CONTRACTS.yml" <<'EOF'
version: 1
contracts:
  - id: ocr.protocol.v1
    assertion: Engines preserve the shared OCR request and result shape.
    authority: user:task:test#turn-1
    between: [ocr.orchestrator, ocr.external]
    surfaces: [interface:OcrEngine, repo:schemas/ocr.json]
    architecture: [architecture:docs/architecture.md#provider-isolation]
    verifies: [command:checks/verify.sh]
  - id: ocr.submit-doc
    assertion: The submission documentation preserves the public job flow.
    authority: user:task:test#turn-1
    between: [ocr.orchestrator, ocr.external]
    surfaces: [interface:SubmitJob]
    architecture: [architecture:README.md#submit-and-observe-a-job]
    verifies: [command:checks/verify.sh]
  - id: ocr.setup-doc
    assertion: The setup documentation preserves the supported local workflow.
    authority: user:task:test#turn-1
    between: [ocr.orchestrator, ocr.external]
    surfaces: [interface:LocalSetup]
    architecture: [architecture:README.md#local-setup]
    verifies: [command:checks/verify.sh]
EOF
git -C "$fixture" add -A
git -C "$fixture" commit -qm seed
discovery_ground=$(git -C "$fixture" rev-parse HEAD)
discovery_tree=$(git -C "$fixture" rev-parse 'HEAD^{tree}')
cat >"$fixture/.invariant/discoveries/ui-event-order.yml" <<EOF
version: 1
id: ui-event-order
status: pending
ground: $discovery_ground
tree: $discovery_tree
domains: []
statement: UI event ordering may need a durable promise.
evidence: [repo:ui/view.txt]
candidates: [contract, architecture]
EOF
git -C "$fixture" add .invariant/discoveries/ui-event-order.yml
git -C "$fixture" commit -qm "queue discovery"

ok() { echo "ok - $1"; }
die() { echo "not ok - $1"; exit 1; }

out=$(cd "$fixture" && "$compat" brief reach --paths ui/view.txt)
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "ordinary UI change gained governance ceremony"
printf '%s\n' "$out" | grep -q '^TOPOLOGY: area.ui$' || die "derived scope missing"
printf '%s\n' "$out" | grep -q '^TOPOLOGY-NEW:' && die "existing UI topology was reported as new"
printf '%s\n' "$out" | grep -q '^DISCOVERY: ui-event-order (pending)$' || die "relevant pending discovery was not visible"
ok "pending discoveries remain visible without changing local reach"

printf 'ui changed\n' >"$fixture/ui/view.txt"
git -C "$fixture" commit -qam "change discovery evidence"
out=$(cd "$fixture" && "$compat" brief reach --paths ui/view.txt)
printf '%s\n' "$out" | grep -q '^DISCOVERY: ui-event-order (needs-review — changed evidence ui/view.txt)$' ||
  die "causally changed discovery evidence was not marked for review"
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "discovery freshness became a landing blocker"
ok "causally suspect discoveries warn without governing"

out=$(cd "$fixture" && "$compat" brief reach --paths .hidden/new.txt "Upper Dir/new.txt" \
  "packages/Fancy App/new.txt" root-new.txt)
printf '%s\n' "$out" | grep -q '^TOPOLOGY: area.root$' || die "root topology missing from committed tree edge case"
printf '%s\n' "$out" | grep -q '^TOPOLOGY: area.upper-dir$' || die "uppercase and spaced area slug changed"
printf '%s\n' "$out" | grep -q '^TOPOLOGY: area.packages$' || die "nested package area missing"
printf '%s\n' "$out" | grep -q '^TOPOLOGY: pkg.fancy-app$' || die "nested package slug changed"
printf '%s\n' "$out" | grep -q '^TOPOLOGY-NEW:' && die "committed tree edge-case topology was reported as new"
ok "committed tree scopes preserve hidden, uppercase, spaced, package, and root-marker behavior"

mkdir -p "$fixture/migrations"
printf 'create table example(id integer);\n' >"$fixture/migrations/001.sql"
out=$(cd "$fixture" && "$compat" brief reach --paths migrations/001.sql)
printf '%s\n' "$out" | grep -q '^TOPOLOGY-NEW: area.migrations$' || die "new area topology was not reported"
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "new topology invented governance reach"
rm -rf "$fixture/migrations"
ok "new topology is advisory and remains semantically local"

out=$(cd "$fixture" && "$compat" brief reach --paths src/ocr/engine.txt --domain ocr.external)
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.protocol.v1 (bounded)$' || die "domain contract not selected"
printf '%s\n' "$out" | grep -q '^AFFECTED: architecture:docs/architecture.md#provider-isolation (bounded)$' || die "domain architecture not selected"
printf '%s\n' "$out" | grep -q '^REVIEW: architecture:docs/architecture.md#provider-isolation' || die "architecture review not emitted"
printf '%s\n' "$out" | grep -q '^REACH: bounded$' || die "accepted domain work is not bounded"
ok "semantic domain selection retrieves architecture and contracts"

out=$(cd "$fixture" && "$compat" brief rows ocr.external)
printf '%s\n' "$out" | grep -q '^ARCHITECTURE architecture:docs/architecture.md#provider-isolation$' ||
  die "domain rows omitted the canonical architecture pointer"
printf '%s\n' "$out" | grep -q '^CONTRACT ocr.protocol.v1 — ' || die "domain contract pointer did not retrieve its promise"
ok "domain pointers provide a thin semantic retrieval index"

out=$(cd "$fixture" && "$compat" brief verifiers --paths src/ocr/engine.txt --domain ocr.external)
printf '%s\n' "$out" | grep -q '^VERIFY: contract:ocr.protocol.v1 command:checks/verify.sh$' || die "contract verifier missing"
printf '%s\n' "$out" | grep -q '^REVIEW: architecture:docs/architecture.md#provider-isolation' || die "architecture review missing"
ok "contracts verify mechanically while architecture retains semantic review"

out=$(cd "$fixture" && "$compat" brief reach --paths schemas/ocr.json)
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.protocol.v1 (bounded)$' || die "contract surface did not resolve mechanically"
out=$(cd "$fixture" && "$compat" brief reach --paths ui/view.txt --interface OcrEngine)
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.protocol.v1 (bounded)$' || die "interface surface did not resolve"
ok "contract surfaces remain mechanically discoverable without routes"

out=$(cd "$fixture" && "$compat" brief reach --paths docs/architecture.md --domain ocr.external)
printf '%s\n' "$out" | grep -q '^REACH: open$' || die "defining material change did not open governance"
ok "defining material changes are open"

sed 's/Submit work and observe its events/Submit work and stream its events/' "$fixture/README.md" >"$fixture/README.tmp"
mv "$fixture/README.tmp" "$fixture/README.md"
out=$(cd "$fixture" && "$compat" brief reach --paths README.md)
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.submit-doc (open)$' || die "changed Markdown section did not reach its contract"
printf '%s\n' "$out" | grep -q 'contract:ocr.setup-doc' && die "unchanged Markdown section reached an unrelated contract"
git -C "$fixture" checkout -q -- README.md
ok "working-tree Markdown hunks route section-specific material"

readme_base=$(git -C "$fixture" rev-parse HEAD)
sed 's/Run the local service/Run the local development service/' "$fixture/README.md" >"$fixture/README.tmp"
mv "$fixture/README.tmp" "$fixture/README.md"
git -C "$fixture" commit -qam "change setup section"
out=$(cd "$fixture" && "$compat" brief reach "$readme_base")
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.setup-doc (open)$' || die "committed Markdown section did not reach its contract"
printf '%s\n' "$out" | grep -q 'contract:ocr.submit-doc' && die "candidate routing selected an unchanged Markdown section"
ok "candidate-tree Markdown hunks route section-specific material"

out=$(cd "$fixture" && "$compat" brief material-changes "$readme_base" HEAD ocr.external)
printf '%s\n' "$out" | grep -q '^MATERIAL-CHANGED: architecture:README.md#local-setup$' || die "changed selected material was not reported"
printf '%s\n' "$out" | grep -q '#submit-and-observe-a-job$' && die "unchanged selected material was reported"
ok "selected governing material changes are section-aware"

out=$(cd "$fixture" && "$compat" brief reach --paths README.md)
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.submit-doc (open)$' || die "hypothetical path check narrowed without diff evidence"
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.setup-doc (open)$' || die "hypothetical path check omitted anchored material"
ok "path-only Markdown checks remain conservatively file-wide"

history_base=$(git -C "$fixture" rev-parse HEAD)
printf '\nChanged.\n' >>"$fixture/docs/architecture.md"
git -C "$fixture" commit -qam "temporarily change architecture"
git -C "$fixture" checkout -q "$history_base" -- docs/architecture.md
git -C "$fixture" commit -qm "restore architecture"
out=$(cd "$fixture" && "$compat" brief reach --history "$history_base")
printf '%s\n' "$out" | grep -q '^AFFECTED: contract:ocr.protocol.v1 (open)$' || die "history reach hid a reverted material change"
out=$(cd "$fixture" && "$compat" brief reach "$history_base")
printf '%s\n' "$out" | grep -q '^REACH: local$' || die "net-tree reach unexpectedly retained a reverted change"
ok "history reach preserves intervening path evidence across reverts"

digest=$(cd "$fixture" && "$compat" brief digest ocr.external | sed 's/^DIGEST: //')
at_digest=$(cd "$fixture" && "$compat" brief digest --at HEAD ocr.external | sed 's/^DIGEST: //')
[ "$digest" = "$at_digest" ] || die "commit-addressed governance digest differs from the same working tree"
sed 's/UI event ordering may need/UI event sequencing may need/' "$fixture/.invariant/discoveries/ui-event-order.yml" >"$fixture/.invariant/discoveries/ui-event-order.tmp"
mv "$fixture/.invariant/discoveries/ui-event-order.tmp" "$fixture/.invariant/discoveries/ui-event-order.yml"
after_discovery=$(cd "$fixture" && "$compat" brief digest ocr.external | sed 's/^DIGEST: //')
[ "$digest" = "$after_discovery" ] || die "non-authoritative discovery entered governing digest"
sed 's/Owns OCR capabilities/Owns OCR execution capabilities/' "$fixture/.invariant/DOMAINS.yml" >"$fixture/.invariant/DOMAINS.tmp"
mv "$fixture/.invariant/DOMAINS.tmp" "$fixture/.invariant/DOMAINS.yml"
after_domain=$(cd "$fixture" && "$compat" brief digest ocr.external | sed 's/^DIGEST: //')
[ "$digest" != "$after_domain" ] || die "domain responsibility change did not change digest"
at_digest=$(cd "$fixture" && "$compat" brief digest --at HEAD ocr.external | sed 's/^DIGEST: //')
[ "$digest" = "$at_digest" ] || die "working governance leaked into commit-addressed digest"
if (cd "$fixture" && "$compat" brief check-digest "$digest" ocr.external >/dev/null 2>&1); then die "stale digest was accepted"; fi
git -C "$fixture" checkout -q -- .invariant/DOMAINS.yml .invariant/discoveries/ui-event-order.yml
ok "digest covers governance and excludes evidence"

printf '  - id: ocr.embedded\n    responsibility: Embedded OCR engine.\n    authority: user:task:test#turn-2\n    parent: ocr\n' >>"$fixture/.invariant/DOMAINS.yml"
out=$(cd "$fixture" && "$compat" brief reach --paths .invariant/DOMAINS.yml)
printf '%s\n' "$out" | grep -q '^REACH: gated$' || die "working-tree governance edit was not conservative"
git -C "$fixture" checkout -q -- .invariant/DOMAINS.yml
ok "existing governance rewrites are conservatively gated"

base=$(git -C "$fixture" rev-parse HEAD)
cat >>"$fixture/.invariant/CONTRACTS.yml" <<'EOF'
  - id: ocr.audit-protocol.v1
    assertion: Governance audits remain executable.
    authority: user:task:test#turn-2
    between: [ocr.orchestrator, ocr.external]
    surfaces: [repo:src/ocr]
    architecture: [architecture:docs/architecture.md#provider-isolation]
    verifies: [command:checks/verify.sh]
EOF
git -C "$fixture" add .invariant/CONTRACTS.yml
git -C "$fixture" commit -qm "add audit protocol contract"
out=$(cd "$fixture" && "$cli" context verifiers --base "$base")
printf '%s\n' "$out" | grep -q '^VERIFY: contract:ocr.audit-protocol.v1 command:checks/verify.sh$' ||
  die "new contract verifier was not selected during governance establishment"
ok "new governance contracts run their declared verifiers"

msg=$(cd "$fixture" && "$compat" brief message "change engine" --unit engine --scope area.src --domain ocr.external)
printf '%s\n' "$msg" | grep -q '^Invariant-Domain: ocr.external$' || die "semantic domain trailer missing"
printf 'changed\n' >>"$fixture/src/ocr/engine.txt"
git -C "$fixture" commit -qam "$msg"
(cd "$fixture" && "$compat" brief trailer HEAD >/dev/null) || die "honest derived scope/domain trailers failed"
ok "commit trailers retain mechanical scope and semantic domain separately"

echo "18 brief checks passed"
