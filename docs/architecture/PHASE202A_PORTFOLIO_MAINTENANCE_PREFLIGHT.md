# Phase 202A — Portfolio-Maintenance P0-Safe Migration Preflight

Status:      HISTORICAL
as_of:       2026-06-05T10:59:04-04:00
Measured at: efcc51365 / not measured

P0-safe portfolio-maintenance cron/timer migration pilot. Same pattern as Phase 200/201. **db_retention
and price-cache are NOT migrated** (destructive / feeds trading) — inventory/diff-plan only.

## Repo state
- Branch: **main** · Head: `fcd03f4 docs: index + state snapshot for Phase 201 ...`

## Safety baseline (verified)
- `ALPACA_MODE=paper` · live **OFF** · Level 7 **PROHIBITED**.
- **Governance migration still clean:** controller timer `active`; 4 retired PHASE41 gov timers
  `disabled` 4/4.
- **Safety net untouched:** `system_freshness_monitor` (`*/20`) + `freshness_watchdog_heartbeat`
  (`*/30`) — 2 active cron.
- No broker / proposal / protection / trading job in scope.

## Backups (pre-migration)
`/tmp/crontab_before_phase202.txt` (437 lines) · `/tmp/user_timers_before_phase202.txt` ·
`/tmp/user_services_before_phase202.txt` · system timers/services backups.

## Candidate safety inspection (grep: broker / proposal / destructive)
| Job | broker | proposal | destructive | classification |
|-----|--------|----------|-------------|----------------|
| `run_pg_backup.sh` | 0 | 0 | file-rotation only (find -delete >30d; no SQL) | **P0-safe** |
| `run_portfolio.sh` | 0 | 0 | 0 | **P0-safe** |
| `run_portfolio_weekly.sh` | 0 | 0 | 0 | **P0-safe** |
| `run_portfolio_monthly.sh` | 0 | 0 | 0 | **P0-safe** |
| `run_lookthrough.sh` | 0 | 0 | 0 | **P0-safe** (read-only analysis) |
| `backup_secrets_state.sh` | 0 | 0 | Drive/file retention rotation only (no SQL) | **P0-safe** |
| `run_price_cache.sh` | 0 | 0 | 0 (but WRITES price cache feeding trading/proposal) | **EXCLUDED — diff-only** |
| `db_retention.py` | 0 | 0 | 14 (DB retention DELETEs) | **EXCLUDED — never this phase** |

Verified: neither backup script contains `DROP`/`TRUNCATE`/`DELETE FROM` — deletes are backup-file
rotation only, so backups are genuinely P0-safe.

## Rollback plan
- Crontab: `crontab /tmp/crontab_before_phase202.txt`.
- Timers: `systemctl --user enable --now <timer>`.
- Legacy lines commented (not deleted) with `# PHASE202_MIGRATED...` markers, reversible.

---
*Preflight clean. 6 P0-safe candidates; price-cache + db_retention excluded; safety net + governance
intact.*
