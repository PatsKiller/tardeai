# CIO Final Truth — isolated-branch baseline

Authority: `READ_ONLY_ADVISORY`. This branch does not merge, deploy, mutate
branch protection, or send live Telegram.

| Field | Value |
|---|---|
| Worktree | `/home/johnclaw/tradeai-wt-cio-final-truth` |
| Branch | `fix/cio-v4-final-truth-acceptance` |
| BASE_SHA | `e20dc5eb80565ced4fa8203291057f34a12af0b3` |
| Remote main at branch creation | `e20dc5eb80565ced4fa8203291057f34a12af0b3` |
| Remote main class | `RELEASE_ATTESTATION_ONLY` |
| Attested runtime content SHA | `9a06cf39f0662c7edf5b96cc08f3a712a46bf865` |
| First parent | `9a06cf39f0662c7edf5b96cc08f3a712a46bf865` |
| PR #312 | Untouched (separate workstream) |
| Created (UTC) | `2026-08-14T21:50:00Z` |

## Non-negotiables

1. The auditor must not mutate the audited book.
2. `reconcile_holdings_canonical_marks.py` is a repair/migration utility, never an acceptance step.
3. Broker MV ≠ analytical mark ≠ analytical MV. Do not overwrite one to equal another.
4. Freshness is `source_as_of`, never `reconciled_at` / generic `updated_at`.
5. Missing evidence is FAIL. Unknown Drive duplicate count is not zero.
6. `PRODUCTION_ACCEPTANCE` is an alias of `CORE_CIO_PRODUCTION_ACCEPTANCE`. Full office acceptance stays FAIL while research is unintegrated.
