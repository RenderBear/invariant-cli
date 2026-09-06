## Agent protocol reference

### Locator namespaces

Use locator namespaces consistently. Validation does not convert one semantic object into another.

| Concept | Accepted form |
|---|---|
| Authority source | `user:task:<id>#<turn>`, `user:url:https://...`, `design:task:<id>`, `design:url:https://...`, `architecture:repo:<path>#<anchor>`, or `design:repo:<path>#<anchor>` |
| Architecture reference | `architecture:<markdown-path>#<heading-slug>` |
| Governance reference | `semantic:<id>`, `domain:<id>`, `contract:<id>`, `constraint:<id>`, or an exact registered architecture reference |
| Surface | `repo:<path>` or `interface:<name>` |
| Evidence | `repo:<path>`, `commit:<ref>`, `interface:<name>`, `task:<id>`, or `url:https://...` |
| Verifier | `command:<executable-path>`, `test:<test-path>`, `schema:<schema-path>`, or `runner:<name>#<target>` |
| Final boundary disposition | `no-record`, `recorded`, or `audit:<id>` |

A domain or contract may use only an architecture reference whose Markdown file and heading exist
in the candidate. A governance architecture reference must already be registered by a candidate
domain or contract. `unresolved` is a valid boundary disposition only while work is active.

Named verifier runners declare their command, working directory, timeout, and cache policy under
`verification.runners` in `.invariant/config.yml`. Python tests automatically use the nearest
tracked `uv.lock` and `pyproject.toml` when present.

### Meaning and standing

Reach is derived from candidate paths, selected domains and interfaces, and accepted governance; it
is not an authority claim. A discovery or audit is evidence, not a governance reference.

During a governance pass, begin without nonexistent domains and select newly created domains in the
final recorded assessment. Invariant accepts them when the candidate establishes those domain
records. A later pass may instead reconcile existing records with changed repository evidence.
Put complete record projections directly on audit findings when the mapping is unambiguous, then
run `invariant governance project <task-id>`. Inspect selected-finding coverage with `invariant
governance coverage <task-id>`; edit the generated adoption draft only for unresolved mappings.

### Prepare structured inputs

Before writing an audit, load `invariant evidence audit schema`. Run `invariant task finish
<task-id>` after committing; it prepares routine assessments, collects exact-tree evidence, and
returns typed actions when semantic input remains. Resolve those actions only through `invariant
task respond <task-id> <action-id> --input <file>`. Use `invariant task assessment prepare <task-id>`
for explicit low-level inspection. When the intent-brief adapter is enabled, load `invariant task
intent-brief schema`; keep its task-local prose separate from repository governance.

Prefer compact JSON for automation. Treat `status: ok, outcome: needs_input` as a successful
suspension for judgment, consume every returned action, and never infer lifecycle state from prose.
Use `invariant task action <task-id> <action-id>` to fetch a response schema and `invariant task
evidence <task-id> [<evidence-id>]` to retrieve captured evidence. Accepted reviews use
`candidate_defects` for blocking problems and `retained_discoveries` for non-blocking audit evidence.
