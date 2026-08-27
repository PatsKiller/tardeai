# SCHWAB-BT-4 — Classification Writeback + Strategy-Grouped Replay

**Date:** 2026-05-22

## What Was Done

1. Created `historical_trade_strategy_classifications` table (87 rows, all human_review_only)
2. Updated `trade_closed.strategy_id` for 76 Schwab trades (was all NULL)
3. Re-ran enterprise backtester — strategy grouping now works

## Strategy Evidence (82 replayed trades)

| Strategy | Count | Win Rate | Profit Factor | Source |
|----------|-------|----------|---------------|--------|
| momentum_scalp | 47 | 34.0% | 0.80 | Schwab (unprofitable) |
| gap_and_go | 29 | 51.7% | 1.71 | Schwab (profitable) |
| swing_breakout | 2 | 100% | 15.94 | Alpaca paper |
| earnings_catalyst | 1 | 100% | 11.32 | Alpaca paper |
| screener | 1 | 100% | 4.19 | Alpaca paper |
| dividend_growth_compounder | 1 | 0% | 0.00 | Alpaca paper |
| swing_trade | 1 | 0% | 0.00 | Alpaca paper |

## Key Finding

**momentum_scalp is unprofitable across 47 Schwab trades** (34% WR, PF 0.80).
This is consistent with the 2 Alpaca paper momentum_scalp losses.
**gap_and_go shows promise** (51.7% WR, PF 1.71 across 29 trades).

## Safety

- All classifications human_review_only=true
- Raw Schwab import rows NOT overwritten (separate table)
- Schwab execution remains DISABLED
- No orders/trades/approvals created
