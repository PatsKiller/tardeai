# Phase 202G — Cadence-Aware Portfolio Controller Redesign (Option B)

Status:      HISTORICAL
as_of:       2026-06-05T12:05:10-04:00
Measured at: efcc51365 / not measured

`scripts/pipelines/run_portfolio_maintenance_pipeline.sh` rewritten: each cadence runs ONLY its own
steps, with its own lock/log/summary — preserving the distinct legacy schedules. Bundled scheduling
is abandoned.

## CLI
`--cadence {daily|weekly|monthly|backup|lookthrough|all}` (required) · `--dry-run` (default) | `--apply`.
`--cadence all` = MANUAL DRY-RUN/TEST ONLY (warns on `--apply`; never scheduled in production).

## Cadence → steps
| cadence | steps | label |
|---------|-------|-------|
| backup | run_pg_backup.sh + backup_secrets_state.sh **env** + **data** | BACKUP (pure; secrets arg-bug fixed) |
| daily | run_portfolio.sh | PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY |
| weekly | run_portfolio_weekly.sh | PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY |
| monthly | run_portfolio_monthly.sh | PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY (LLM, ~15 min) |
| lookthrough | run_lookthrough.sh | READ_ONLY_SNAPSHOT |
| all | all of the above | manual test only |
| (always) | price_cache, db_retention | EXCLUDED_NOT_RUN |

## Per-cadence isolation
- Summary: `data/runtime/portfolio_maintenance_<cadence>_last_run.json`
- Logs: `logs/pipelines/portfolio-maintenance/<cadence>/`
- Lock: `/tmp/pipeline_portfolio-maintenance-<cadence>.lock`
- Safety asserts (live-off, Level-7) + no-broker attestation; non-cascading; DRY_RUN default.

## Corrections baked in
- Advisory-draft reports explicitly LABELED (not "static report").
- `secrets_state_backup` now invoked correctly with `env` and `data` (was the rc=2 bug).
- Distinct cadences mean monthly's 15.6-min LLM run never lands on a daily schedule.

## Status
Redesigned + syntax-OK. NOT scheduled. NOT retiring legacy. Dry-runs in 202H; backup-cadence apply
pilot in 202I.
