# Task contract adapter

Preserve the user's original request and derive a local task contract from it. Make the
expanded goal, outcomes, acceptance conditions, and constraints explicit without turning them into
repository governance.

Choose a proportional verification level from semantic reach and risk, not line count alone:

- `inspection` for local presentation or documentation changes whose acceptance can be observed
  directly;
- `targeted` for bounded behavior covered by focused existing checks;
- `broad` for cross-domain, security, persistence, compatibility, or similarly high-risk changes.

Do not manufacture a persisted unit test for every acceptance condition. Prefer an existing check,
inspection, type check, schema comparison, screenshot, or explicit review when that is sufficient.
The contract is disposable task context stored under Git-local Invariant runtime.
