# Phase 205 — Legacy Backup Path Retirement (2026-06-06, operator-approved)

Status:      HISTORICAL
as_of:       2026-06-06T08:41:23-04:00
Measured at: efcc51365 / not measured

Operator approved retiring the legacy backup path after the backup-cadence timer's first auto-fire
(Sat 2026-06-06 02:30:42 EDT) compared CLEAN (PASS, 0 unacceptable). Retired REVERSIBLY.

## What the new cadence covers
`tradeai-portfolio-backup-cadence.timer` (DAILY 02:30) → `run_portfolio_maintenance_pipeline.sh
--cadence backup --apply` runs: portfolio_backup (run_pg_backup.sh) + secrets_backup_env
(backup_secrets_state.sh env). Last run ok (pg + secrets-env both ok; price_cache/db_retention excluded).

## Retired (reversible) — fully redundant with the cadence
1. **portfolio-backup.timer** (systemd, DAILY 02:00, run_pg_backup.sh) — identical pg backup to the cadence
   at 02:30. Action: `systemctl --user disable --now portfolio-backup.timer` → disabled/inactive.
2. **secrets-env daily cron** (`30 5 * * * … backup_secrets_state.sh env`) — identical to cadence
   secrets_backup_env. Action: commented in crontab with `# [RETIRED 2026-06-06 …]` marker.

## KEPT (NOT retired) — coverage gap, would lose backups
3. **secrets-data weekly cron** (`45 5 * * 0 … backup_secrets_state.sh data`, Sun 05:45) — RETAINED.
   Reason: secrets-data lives only in `--cadence weekly`, which is **not scheduled**; and `run_weekly()`
   also runs `portfolio_weekly_report` (already run by portfolio-weekly.timer Sun 20:00), so scheduling
   the weekly cadence purely to cover secrets-data would double-run the weekly report. Retiring this cron
   now would silently stop weekly data backups → kept. (STOP-on-mismatch.)

## Follow-up options for the weekly-data leg (operator decision)
- (a) Split secrets_backup_data into its own dedicated weekly timer (no report overlap), then retire the cron; OR
- (b) Leave the legacy data-weekly cron as the canonical weekly data backup (it works, runs Sun 05:45); OR
- (c) Refactor run_weekly so the report step is idempotent/guarded against the existing weekly timer.

## Restore path (full reversal)
- `crontab data/runtime/legacy_backup_retirement_20260606/crontab.before.bak`
- `systemctl --user enable --now portfolio-backup.timer`
State snapshot: data/runtime/legacy_backup_retirement_20260606/ (crontab.before.bak, timer_state.before.txt).

## Verification
portfolio-backup.timer disabled/inactive; env-daily cron commented; data-weekly cron intact; cadence
timer enabled, next Sun 02:30. No backup coverage lost (daily pg + daily secrets-env now via cadence;
weekly data via retained legacy cron).

## Safety
No broker/order/GO-WAIT/strategy/live changes. Backup scheduling only; reversible; state backed up first.

---
## UPDATE — weekly-data leg folded into cadence (operator chose option a, 2026-06-06)
Operator selected: fold secrets_backup_data into the daily backup cadence with a weekly staleness gate.
- `run_portfolio_maintenance_pipeline.sh run_backup()` now runs secrets_backup_data when the stamp
  `data/runtime/last_secrets_data_backup.stamp` is ≥6 days old (or missing); else GATED_SKIP_FRESH.
  Stamp touched only on success. `run_weekly()` no longer runs secrets-data (single owner).
- Seeded a fresh data backup via the new path (data_backup_20260606_083953.tar.gz.gpg, 48M → Drive) and
  anchored the stamp before retiring the cron — no coverage gap.
- **Legacy data-weekly cron RETIRED** (commented). All 3 legacy backup paths now retired; the
  `tradeai-portfolio-backup-cadence.timer` (daily 02:30) is the SOLE owner of pg + secrets-env (daily) +
  secrets-data (weekly-gated).

### Final state
- portfolio-backup.timer: disabled/inactive · env-daily cron: commented · data-weekly cron: commented
- cadence timer: enabled, next Sun 02:30 · data stamp: fresh (2026-06-06)
- Restore: `crontab data/runtime/legacy_backup_retirement_20260606/crontab.before.bak` +
  `systemctl --user enable --now portfolio-backup.timer`. Before/after crontabs both snapshotted.

### Safety
Backup scheduling only; reversible; fresh backup taken before retirement; no broker/order/GO-WAIT/
strategy/live changes.
