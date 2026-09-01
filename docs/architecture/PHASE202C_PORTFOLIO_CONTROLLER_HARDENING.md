# Phase 202C — Portfolio-Maintenance Controller Hardening

Status:      HISTORICAL
as_of:       2026-06-05T11:00:13-04:00
Measured at: efcc51365 / not measured

`scripts/pipelines/run_portfolio_maintenance_pipeline.sh` upgraded from 199E skeleton to a real
executor for **P0-safe** jobs only. No schedule wired yet (202G).

## Properties (same shape as the proven governance controller)
- Strict bash; safe env load; `assert_no_live_trading` + `assert_no_level7` (abort nonzero) + a
  P0-safe attestation line.
- **DRY_RUN=1 default**; `--apply` runs the P0-safe steps.
- Per-run log → `logs/pipelines/portfolio-maintenance/portfolio_<UTC>.log`.
- `flock` lock (`/tmp/pipeline_portfolio-maintenance-pipeline.lock`).
- Named `pm_step`s with START/END/status/ms; **non-cascading** (failed step recorded, others continue).
- Summary JSON → `data/runtime/portfolio_maintenance_pipeline_last_run.json`.

## P0-safe steps (run)
1. `portfolio_backup` → run_pg_backup.sh
2. `portfolio_daily_report` → run_portfolio.sh
3. `portfolio_weekly_report` → run_portfolio_weekly.sh
4. `portfolio_monthly_report` → run_portfolio_monthly.sh
5. `portfolio_lookthrough` → run_lookthrough.sh
6. `secrets_state_backup` → backup_secrets_state.sh

## Excluded (echo-only `EXCLUDED_NOT_RUN`, never executed even with --apply)
- `price_cache` — writes price cache feeding trading/proposal (diff-only, future gate)
- `db_retention` — destructive DB deletes (prohibited this phase, future deletion-set diff)

These appear in the summary JSON `excluded` array + as EXCLUDED_NOT_RUN steps, so they're visibly
known-excluded, not silently dropped.

## NOT in this controller
- No destructive job, no price-cache write, no broker/trading/proposal/protection/Hermes/LLM step.
- Safety net untouched.

---
*Hardened, not scheduled. DRY_RUN default; P0-safe steps only; destructive/price-cache excluded.*
