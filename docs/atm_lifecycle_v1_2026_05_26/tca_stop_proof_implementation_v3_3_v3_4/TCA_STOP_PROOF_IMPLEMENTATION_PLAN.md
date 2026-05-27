# v3.3/v3.4 TCA + Stop Proof Implementation Plan

## Schema Changes
- 4 nullable columns on paper_trades (non-destructive)
- 2 indexes on new columns

## Scripts to Patch
1. `scripts/alpaca_paper_adapter.py` — capture order_submitted_at, order_filled_at, broker_order_id
2. `scripts/unified_stop_supervisor.py` — store stop_order_id after stop placement
3. `scripts/paper_execution_quality_analyzer.py` — read timing fields for TCA
4. `scripts/atm_position_reconciler.py` — add read-only stop verification

## API Endpoints to Add
- `GET /api/v2/atm/stop-proof` — per-trade stop verification status
- `GET /api/v2/atm/execution-timing-health` — timing field population summary

## UI Panels to Add
- StopProofPanel in ATM Control Room
- ExecutionTimingPanel in ATM Control Room or ExecutionQuality page

## Validation
1. Schema migration dry-run
2. Verify columns exist with SELECT
3. Test API endpoints return correct shapes
4. Frontend build clean
5. Screenshots captured
6. No orders placed, no stops modified

## Rollback
```sql
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_submitted_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS order_filled_at;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_order_id;
ALTER TABLE paper_trades DROP COLUMN IF EXISTS stop_verified_at;
```
Plus `git revert HEAD`.
