# Phase 204I — Backup Cadence Schedule Report

Status:      HISTORICAL
as_of:       2026-06-05T12:23:35-04:00
Measured at: efcc51365 / not measured

Diff passed (204H) → the refined **backup cadence** is scheduled. **Legacy retained; nothing retired.**
- **Scheduled: YES.** Mechanism: **systemd user timer** (project convention).
  - Service `tradeai-portfolio-backup-cadence.service` →
    `run_portfolio_maintenance_pipeline.sh --cadence backup --apply`
  - Timer `tradeai-portfolio-backup-cadence.timer` → `OnCalendar=*-*-* 02:30:00` (daily).
- **Cadence:** daily 02:30 — after the legacy daily pg backup (02:00) to avoid simultaneous pg_dumps
  during parallel observation; preserves the daily backup cadence.
- **Scope:** ONLY pg_backup + secrets-env. NOT daily/weekly/monthly reports, NOT lookthrough, NOT
  secrets-data (weekly cadence), NOT db_retention, NOT broker/proposal/protection/trading.
- **Next run:** Sat 2026-06-06 02:30.
- **Legacy still active: YES** (`portfolio-backup.timer` active; 2 secrets cron lines active) — parallel observation.
- **Logs:** `logs/pipelines/portfolio-maintenance/backup/`. **Lock:** `/tmp/pipeline_portfolio-maintenance-backup.lock`.
- **Rollback:** `systemctl --user disable --now tradeai-portfolio-backup-cadence.timer`.
- **Observation requirement before retirement:** observe ≥1 automatic 02:30 cycle clean + diff vs
  legacy, THEN retire only the redundant legacy backup line (Phase 205). No retirement now.
