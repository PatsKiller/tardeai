# Broker Stop Proof Gap Analysis

## Current State

| Metric | Value |
|--------|-------|
| Open trades | 3 |
| With DB stop_loss | 3 |
| Missing DB stop | 0 |
| Broker stop order ID stored | NO — no column exists |
| Broker stop verification | NONE — no real-time check |
| Reconciler frequency | 2x/day (alpaca_paper_reconciler.py) |

## Where Is Stop Stored?

- `paper_trades.stop_loss` — DB stop price (always present for open trades)
- No `stop_order_id` column in paper_trades
- No `broker_stop_verified_at` column
- `unified_stop_supervisor.py` updates stop_loss in DB but does NOT verify broker side

## What Is Missing

1. **No broker stop order ID** — when a stop is placed via Alpaca, the order ID is not stored
2. **No real-time verification** — no script asks "does Alpaca have a stop for this position?"
3. **No stop-mismatch detection** — DB says $23.61 but broker might have $23.00 or nothing
4. **No stop-placement audit trail** — when stop was placed, modified, or cancelled

## Proposed Fix

1. Add `stop_order_id` and `stop_verified_at` columns to paper_trades
2. After placing stop via Alpaca, store the `order_id`
3. Add read-only Alpaca stop verification to reconciliation cron
4. Surface stop proof in ATM Control Room (DB stop + broker stop + match status)
