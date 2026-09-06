# Product roadmap

The core lifecycle, zero-configuration shell/Python verification, and delta-oriented action
transport are implemented. The remaining ergonomic work should preserve those mechanics and avoid
adding new lifecycle stages.

## 1. Stage-aware command discovery

- Add `invariant next [task-id]` as the single orientation command.
- Return the current stage, reason for suspension, valid next commands, and whether semantic
  judgment or explicit approval is required.
- Make invalid commands suggest the nearest valid command in the current namespace.
- Keep the default response compact; route explanations to an explicit expansion command.

Acceptance: an agent starting with only `invariant status` can complete a governance pass without
opening the workflow handbook.

## 2. Deterministic orchestration facade

- Add `invariant governance continue <task-id>`.
- Let it perform every deterministic transition available: validate the audit, calculate finding
  coverage, project unambiguous records, construct the candidate, and run verification.
- Stop only for semantic judgment, explicit assisted-mode approval, or a mechanical failure.
- Preserve the existing lower-level commands for diagnostics and automation.

Acceptance: the common governance path pauses only at audit judgment and final semantic review.

## 3. Harden the declaration/receipt boundary

- Keep governance limited to what must be true and which repository witness supports it.
- Ensure resolved argv, working directory, timeout, environment, cache decision, duration, and logs
  exist only in ignored runtime receipts.
- Review whether expert named-runner definitions should remain tracked configuration or move to a
  separately discoverable toolchain surface.
- Add an inspection command that explains how a witness resolved without requiring users to read
  configuration or runtime YAML.

Acceptance: changing verification infrastructure does not rewrite governance unless the witness or
the invariant itself changes.

## 4. Ergonomic regression coverage

- Add exact-candidate fixtures for standalone shell, Python/uv, Node, and mixed-language projects.
- Cover detached candidates with no pre-existing local environment.
- Add fixtures for exceptional custom runners without making them part of the ordinary path.
- Enforce byte budgets for default lifecycle responses and ensure expanded APIs retain all detail.
- Measure command count, repeated evidence, and model-visible bytes for a representative governance
  pass.

Acceptance: ordinary lifecycle responses remain below 2 KB, and a full pass does not repeat any
  evidence body unless explicitly expanded.
