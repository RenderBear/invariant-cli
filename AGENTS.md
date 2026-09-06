# AGENTS.md

## Critical rules

- **Never push to the remote.** No `git push` under any circumstances. Committing locally is fine; publishing is the user's decision.
- **Repository-local skills are product source, not active agent skills.** Do not use `skills/intent-*` as an operating workflow unless the user explicitly asks you to run or test them.
- **Do not add migrations.** This repository does not need backward-compatibility or migration paths unless the user explicitly requests one; replace obsolete formats and locations directly.

## Verification

Run every shell test:

```bash
for test_file in tests/test-*.sh; do sh "$test_file" || exit; done
uv run pytest
uv build --no-sources
```

Use POSIX shell for scripts and test deterministic mechanics rather than policy wording.
