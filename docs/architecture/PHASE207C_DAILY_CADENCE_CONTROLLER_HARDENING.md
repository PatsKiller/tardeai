# Phase 207C — Daily Cadence Controller Hardening — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:50:07-04:00
Measured at: efcc51365 / not measured

## Already-present (verified, no change needed)
`scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence daily`:
- runs **only** `run_daily()` → `bash linux_launchers/run_portfolio.sh` (case isolation; no backup/
  weekly/monthly/lookthrough).
- labels the step **`PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`**.
- `price_cache` + `db_retention` always `EXCLUDED_NOT_RUN`; secrets-data not run (backup-cadence owned).
- writes `data/runtime/portfolio_maintenance_daily_last_run.json`; logs to
  `logs/pipelines/portfolio-maintenance/daily/`; uses the cadence-specific lock
  `portfolio-maintenance-daily`.
- `assert_no_live_trading` + `assert_no_level7` + P0-safe banner at start.

## Added this phase (the one gap)
`assert_review_only_chain` — a **fail-closed** static guard. Before running a review-only report step it
scans the launcher chain (`run_portfolio.sh` + `portfolio_orchestrator.py`) for any broker/order/stop
**execution** call-site (`submit_order|place_order|cancel_order|replace_order|move_stop|update_stop` `(`).
If found, the step is **BLOCKED** (recorded `SAFETY_BLOCKED_EXEC_PATH`, `overall=degraded`) and NOT run —
drafts stay drafts, nothing executes. Wired into `run_daily()`.

Verified: `bash -n` OK; the guard **passes** the real daily chain (no broker/order/stop exec present),
so normal review-only operation is unaffected. The backup cadence is untouched (only `run_daily` changed).
