# Classifier Source/Writer Alignment Audit

**Date:** 2026-05-29
**Status:** FIXED (commit ae8efe0, 2026-05-28)

## Problem

The classifier read from the `trades` view (UNION of paper_trades + trade_transactions) but wrote to `strategy_backtest_trades`. Since `trade_transactions` has no `strategy_id` column, those rows always appeared unclassified regardless of backtest row state. This caused:
- Same 55 trades resurfacing after every apply
- Batch 2 producing 0 updates (wasted LLM calls)
- Confusion about classification completeness

## Fix Applied

### `--source` flag (commit ae8efe0)

| Mode | Read | Write | Apply allowed |
|------|------|-------|---------------|
| `--source strategy_backtest_trades` | `strategy_backtest_trades` directly | `strategy_backtest_trades` by row id | YES |
| `--source trades_view` | `trades` view | N/A | NO — trade_transactions has no strategy_id |

### Safety gates
- `--apply` requires explicit `--source`
- `--apply --source trades_view` blocked with clear error
- Default (no `--source`) uses `strategy_backtest_trades` for dry-run
- Write uses row `id` instead of symbol match (prevents cross-update)

### Additional fixes
- `--symbols` flag for targeted classification
- `num_ctx=4096` for gemma3:12b (prevents VRAM overcommit)
- Default model changed to gemma3:12b
- Removed stale `cur.fetchall()` bug that consumed query results

## Current State

| Metric | Value |
|--------|-------|
| strategy_backtest_trades classified | 3,592/3,593 (99.97%) |
| Remaining unclassified | 1 (SHFS id=860, no enrichment data) |
| trades view unclassified | 153 (trade_transactions — expected, no write target) |
| Source/writer mismatch | RESOLVED |
