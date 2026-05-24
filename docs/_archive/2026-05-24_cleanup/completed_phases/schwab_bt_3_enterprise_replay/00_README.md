# SCHWAB-BT-3 — Enterprise Backtester Replay

**Date:** 2026-05-22

## Results

| Metric | Value |
|--------|-------|
| Total signals | 85 |
| Completed replays | 82 |
| Failed (delisted/no data) | 3 |
| Win rate | 42.7% |
| Profit factor | 1.21 |
| Avg return | +0.58% |
| Avg hold | 1.8 days |
| OHLC coverage | 100% |
| Outcome match vs actual | 54.9% |

## Per-Strategy Breakdown

| Strategy | Count | Win Rate | Profit Factor |
|----------|-------|----------|---------------|
| unknown (Schwab, no strategy_id) | 74 | 41.9% | 1.13 |
| swing_breakout | 2 | 100% | 15.94 |
| momentum_scalp | 2 | 0% | 0.00 |
| earnings_catalyst | 1 | 100% | 11.32 |
| screener | 1 | 100% | 4.19 |
| dividend_growth_compounder | 1 | 0% | 0.00 |
| swing_trade | 1 | 0% | 0.00 |

## Key Findings

1. **74 Schwab trades replayed as strategy_id=unknown** because trade_closed
   has NULL strategy_id. The SCHWAB-BT-2 classifier output is in JSON only,
   not written to DB yet.

2. **Schwab day-trading performance:** 41.9% WR, PF 1.13 — marginally profitable.
   Consistent with the momentum/scalp classification from BT-2.

3. **All 11 Alpaca paper trades replayed** with their assigned strategy_ids.

4. **Replay vs actual divergence:** 54.9% outcome match. The replay uses
   daily OHLC bars which can't capture intraday fills exactly.

## What Was NOT Changed

- No Schwab execution enabled
- No strategy activation changed
- No orders/trades/approvals created
- All output is evidence-only, human_review_only
