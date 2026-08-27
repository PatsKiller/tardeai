# Classifier Source/Writer Mismatch Audit

**Date:** 2026-05-28

## The Mismatch

| Component | Before Fix | After Fix |
|-----------|-----------|-----------|
| Read source | `trades` view (UNION of paper_trades + trade_transactions) | Explicit `--source` flag |
| Write target | `strategy_backtest_trades` | Matches `--source` |
| Resurfacing | Same 55 trades always appear "unclassified" | Fixed: `--source strategy_backtest_trades` reads/writes same table |

## Root Cause

The `trades` view is a UNION of:
1. `paper_trades` (has `strategy_id` column)
2. `trade_transactions` (NO `strategy_id` column — physically cannot be updated)

The classifier read from `trades` (finding trade_transactions rows as "unclassified") but wrote to `strategy_backtest_trades`. Since `trade_transactions` has no `strategy_id` column, those rows always appear unclassified regardless of what the classifier writes to `strategy_backtest_trades`.

## Fix Applied

Added `--source` flag with two modes:

### `--source strategy_backtest_trades` (new, recommended)
- Reads unclassified rows directly from `strategy_backtest_trades`
- Writes to `strategy_backtest_trades` by row `id` (not by symbol match)
- No resurfacing: reads and writes the same table
- Required for `--apply`

### `--source trades_view` (read-only)
- Reads from the `trades` view (old behavior)
- **Cannot `--apply`**: trade_transactions has no strategy_id column
- Useful for dry-run analysis only
- Fails closed with clear error if `--apply` attempted

### Apply safety gates
- `--apply` requires explicit `--source`
- `--apply --source trades_view` is blocked with error message
- Default (no `--source`) uses `strategy_backtest_trades` for dry-run

## Additional fixes
- Removed stale `cur.fetchall()` that was consuming query results before processing
- Added `num_ctx=4096` for gemma3:12b to prevent VRAM overcommit
- Default model changed to gemma3:12b (primary classifier model)
- Added `--symbols` flag for targeted classification
