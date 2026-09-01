# Phase 201F — Portfolio-Maintenance Migration Preflight (design only)

Status:      HISTORICAL
as_of:       2026-06-05T10:45:19-04:00
Measured at: efcc51365 / not measured

Inventory of portfolio-maintenance jobs for a future pilot. **No runtime change in Phase 201.**

## Candidates
| Job | Schedule | Command | Purpose | Writes_to | Lock/Log | Broker refs |
|-----|----------|---------|---------|-----------|----------|-------------|
| `portfolio-backup.timer` | Sat | `linux_launchers/run_pg_backup.sh` | Postgres backup | backup files | — | none |
| `portfolio-daily.timer` | Mon | `linux_launchers/run_portfolio.sh` | daily portfolio report | report artifacts/DB snapshot | — | read-only |
| `portfolio-weekly.timer` | Sun | `linux_launchers/run_portfolio_weekly.sh` | weekly report | report artifacts | — | read-only |
| `portfolio-monthly.timer` | monthly | `linux_launchers/run_portfolio_monthly.sh` | monthly report | report artifacts | — | read-only |
| `portfolio-lookthrough.timer` | Sun | `linux_launchers/run_lookthrough.sh` | holdings look-through analysis | analysis artifacts | — | read-only |
| `portfolio-price-cache.timer` | Sun | `linux_launchers/run_price_cache.sh` | refresh quote/price cache | price cache table | — | **Alpaca paper read** (quotes) |
| `backup_secrets_state.sh` (cron) | ×2 | `scripts/backup_secrets_state.sh` | encrypted offsite backup (.env+data → Drive) | Drive | — | **0** (verified) |
| `db_retention.py` (cron) | — | `scripts/db_retention.py` | retention pruning per policy | DB deletes (policy) | — | **0** (verified) |

## Safety notes
- All are read-only reporting / backups / cache, EXCEPT:
  - `price-cache` writes the price cache (read-only Alpaca **paper** quote fetch; no orders/holdings).
  - `db_retention` performs DB deletes per retention policy (must be reviewed — see 201G P1).
- **None** submit orders, mutate holdings, generate proposals, touch protection/GO-WAIT/strategy, or
  use a live broker endpoint.

## Excluded (not portfolio-maintenance)
- `portfolio-server.service` (24/7 v3 API — keep as service, not a maintenance job).
- All trading / proposal / ATM / protection / broker / Hermes / LLM / market-feed jobs.

## DB-write / file-write summary
- File writes: backups, report MD/JSON, lookthrough analysis. DB writes: daily snapshot rows
  (portfolio state), price cache rows, retention deletes. None affect trade state or risk gates.

---
*Design inventory only. 8 candidates; price-cache + db_retention flagged for careful handling (201G).*
