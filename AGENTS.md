# AGENTS.md

## Critical rules

- **Commit changes directly to local main.**
- **Never push to the remote.** No `git push` under any circumstances, publishing is the user's decision.
- **Repository-local skills are product source, not active agent skills.** Do not use `skills/intent-*` as an operating workflow unless the user explicitly asks you to run or test them.
- **Do not add migrations.** This repository does not need backward-compatibility or migration paths unless the user explicitly requests one; replace obsolete formats and locations directly.
- **Keep tests at the product boundary.** Retain or add tests only when they exercise observable `invariant` command behavior or Git mechanics. Do not test documentation parity, prose wording, private helper structure, or standalone styling utilities.

