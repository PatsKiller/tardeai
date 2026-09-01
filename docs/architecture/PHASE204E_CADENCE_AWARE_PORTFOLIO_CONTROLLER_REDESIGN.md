# Phase 204E — Cadence-Aware Portfolio Controller (implemented)

Status:      HISTORICAL
as_of:       2026-06-05T12:08:22-04:00
Measured at: efcc51365 / not measured

The cadence-aware redesign required here was implemented in the Option-B work (committed `23aa38e`):
`scripts/pipelines/run_portfolio_maintenance_pipeline.sh` with `--cadence
{backup|daily|weekly|monthly|lookthrough|all}` + `--dry-run`/`--apply`, per-cadence lock/log/summary,
advisory-draft reports labeled `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`, lookthrough `READ_ONLY_SNAPSHOT`,
and price_cache + db_retention always `EXCLUDED_NOT_RUN`. `--cadence all` is MANUAL_TEST_ONLY.
The backup cadence now includes the **fixed** secrets backup (env + data). See
`PHASE202G_CADENCE_AWARE_PORTFOLIO_CONTROLLER_REDESIGN.md` for the full spec.
