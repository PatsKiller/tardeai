# ATM Recurring Reconciliation Cron v2.0 Report

**Date:** 2026-05-27  

## Files Added/Changed

| File | Action |
|------|--------|
| `scripts/atm_position_reconciler.py` | NEW — reconciliation audit script |
| `sql/atm_reconciliation_tables.sql` | NEW — audit tables DDL |
| Crontab | 2 new entries added |

## DB Tables Created

- `atm_position_reconciliation_runs` — one row per audit run
- `atm_position_reconciliation_items` — one row per position per run

## Cron Entries

```
# Every 15 min during market hours
*/15 9-16 * * 1-5  safe_flock → atm_position_reconciler.py --audit-only --write-audit

# EOD snapshot at 4:45 PM ET
45 16 * * 1-5  safe_flock → atm_position_reconciler.py --audit-only --write-audit (dated output)
```

## Adaptations Made

1. Added `.env` loading via `dotenv` (project uses DB_HOST/DB_USER/DB_PASSWORD, not DATABASE_URL)
2. Constructed DATABASE_URL from DB_* env vars as fallback
3. Adapted SQL query: replaced missing columns (lifecycle_id, strategy_family, broker, etc.) with empty defaults
4. Added `(exit_reason IS NULL OR exit_reason = '')` filter matching project convention
5. Fixed all `json.dumps` calls with `default=str` for datetime serialization

## Manual Dry-Run Result

```json
{
  "db_open_count": 3,
  "journal_open_count": 3,
  "matched_count": 3,
  "mismatch_count": 0,
  "status": "healthy"
}
```

## Audit-Write Result

- Run row inserted: `atmrecon_733b522340a95929`
- 3 item rows: CMCSA, AGNC, NWG — all `matched_open` / `ok`
- paper_trades: UNCHANGED
- Orders placed: NONE

## Safety

- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Default mode: `--audit-only` (cannot modify paper_trades)
- No orders placed
- No positions modified

## Rollback

```bash
# Remove cron
crontab -l | grep -v 'atm_position_reconciler' | crontab -

# Drop tables
psql -c "DROP TABLE IF EXISTS atm_position_reconciliation_items; DROP TABLE IF EXISTS atm_position_reconciliation_runs;"

# Remove script
rm scripts/atm_position_reconciler.py sql/atm_reconciliation_tables.sql
```
