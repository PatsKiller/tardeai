# v3.3/v3.4 Implementation Options

## Minimal Safe Implementation

1. Add 4 columns to paper_trades: order_submitted_at, order_filled_at, stop_order_id, stop_verified_at
2. Populate order_filled_at from Alpaca fill in alpaca_paper_adapter.py
3. Add read-only Alpaca stop query to reconciliation cron
4. Surface stop proof in ATM Control Room
5. Backfill order_filled_at from Alpaca order history where available

## Full Implementation

Everything above plus:
1. Complete order lifecycle state machine (submitted → acked → partial → filled → cancelled)
2. Order lifecycle events table
3. Stop placement/modification audit trail
4. Near-real-time TCA (not just EOD)
5. Stop proof panel with broker vs DB comparison

## DB Changes Needed

```sql
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_submitted_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS order_filled_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_order_id TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS stop_verified_at TIMESTAMPTZ;
```

## Risk/Safety

- Column additions are non-destructive (nullable, no default change)
- Backfill from Alpaca API is read-only query
- Stop verification is read-only query
- No order placement or modification
