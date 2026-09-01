# Phase 202B — P0-Safe Portfolio-Maintenance Job Selection

Status:      HISTORICAL
as_of:       2026-06-05T10:59:04-04:00
Measured at: efcc51365 / not measured

6 P0-safe jobs selected for the controller (reports + backups + read-only snapshot). All verified:
0 broker refs, 0 proposal/GO-WAIT/strategy refs, no production-data deletion.

## Selected (P0-safe)
| Job | Current unit/cron | Schedule | Script | Purpose | Writes_to | Log | P0-safe reason |
|-----|-------------------|----------|--------|---------|-----------|-----|----------------|
| portfolio-backup | `portfolio-backup.timer` | Sat | `linux_launchers/run_pg_backup.sh` | Postgres dump | backup files (+ rotate >30d) | backup log | DB read→dump; deletes only old backup FILES |
| portfolio-daily | `portfolio-daily.timer` | Mon | `linux_launchers/run_portfolio.sh` | daily portfolio report | report artifacts / state snapshot | log | report only; 0 destructive |
| portfolio-weekly | `portfolio-weekly.timer` | Sun | `linux_launchers/run_portfolio_weekly.sh` | weekly report | report artifacts | log | report only |
| portfolio-monthly | `portfolio-monthly.timer` | monthly | `linux_launchers/run_portfolio_monthly.sh` | monthly report | report artifacts | log | report only |
| portfolio-lookthrough | `portfolio-lookthrough.timer` | Sun | `linux_launchers/run_lookthrough.sh` | holdings look-through | analysis artifacts | log | read-only analysis |
| secrets/state backup | `backup_secrets_state.sh` (cron ×2) | — | `scripts/backup_secrets_state.sh` | encrypted offsite backup → Drive | Drive (+ rotate) | log | backup only; deletes old Drive backups only |

## Per-job migration detail
- **Proposed controller step:** each becomes a named `pm_step` in `run_portfolio_maintenance_pipeline.sh --apply`.
- **DB writes:** only `portfolio-daily` (portfolio-state snapshot rows — not trade state) and the
  backups (no DB writes). No deletes of production data.
- **Output diff method:** `compare_portfolio_maintenance_outputs.py` — backup file present + report
  files match (modulo timestamp/run_id) + snapshot row present.
- **Rollback method:** legacy timers/cron stay active (parallel observation) until diff passes;
  retire = disable timer (`enable --now` to restore) / comment cron with `PHASE202_MIGRATED` marker.

## Excluded from active steps (echo-only `EXCLUDED_NOT_RUN` in controller)
- `run_price_cache.sh` (price-cache — feeds trading/proposal) and `db_retention.py` (destructive).
  See `PHASE202B_EXCLUDED_PORTFOLIO_JOBS.md`.

---
*6 P0-safe jobs; reports/backups/read-only only; price-cache + db_retention excluded.*
