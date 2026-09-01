# Phase 179C: Current Paper Trade Statistics Report

Status:      HISTORICAL
as_of:       2026-06-01T23:21:01-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY — Live trading PROHIBITED — Level 7 PROHIBITED

## Summary

| Metric | Value |
|--------|-------|
| Total paper trades | 44 |
| Closed (usable) | 24 |
| Open | 6 |
| Cancelled | 14 |
| Period | 2026-05-06 to 2026-06-01 (26 days) |
| Avg trades/day | 4.0 |
| Readiness Level | **P0 — Not Enough Data** |

## Trade Size

| Metric | Value |
|--------|-------|
| Avg notional | $2,626.83 |
| Median notional | $2,975.44 |
| Max trade | $3,073.77 |
| Min trade | $1,892.02 |
| Total notional traded | $115,580.57 |
| Avg shares | 387 |
| Avg risk per trade | $116.69 |

## Performance (24 Closed Trades)

| Metric | Value |
|--------|-------|
| Win rate | 45.8% |
| Profit factor | 6.35 |
| Expectancy | $77.21/trade |
| Net PnL | $1,853.13 |
| Avg R | 0.919 |
| Max drawdown | $225.00 |
| Best single trade | $315.69 |
| Worst single trade | -$225.00 |

## Strategy Distribution

| Strategy | Total | Closed | Win Rate | Net PnL |
|----------|-------|--------|----------|---------|
| swing_breakout | 12 | 6 | 50.0% | $266.71 |
| swing_trade | 7 | 5 | 20.0% | $247.46 |
| momentum_scalp | 7 | 4 | 50.0% | $379.67 |
| dividend_growth_compounder | 5 | 3 | 100.0% | $56.03 |
| earnings_catalyst | 4 | 2 | 50.0% | -$203.15 |
| fib_retracement_bounce | 2 | 2 | 100.0% | $485.64 |
| screener | 2 | 1 | 100.0% | $202.80 |
| reit_income | 2 | 1 | 100.0% | $5.45 |
| gap_and_go | 1 | 0 | N/A | $0.00 |

## Journal/Field Completeness (Closed Trades)

| Field | Present | Pct | Status |
|-------|---------|-----|--------|
| strategy_id | 24/24 | 100% | PASS |
| exit_reason | 24/24 | 100% | PASS |
| dollar_size | 24/24 | 100% | PASS |
| entry_price | 24/24 | 100% | PASS |
| dollar_risk | 23/24 | 96% | PASS |
| stop_loss | 23/24 | 96% | PASS |
| target | 23/24 | 96% | PASS |
| market_regime | 21/24 | 88% | WARN |
| proposal_id | 21/24 | 88% | WARN |
| pnl | 18/24 | 75% | FAIL |
| exit_price | 18/24 | 75% | FAIL |
| r_multiple | 16/24 | 67% | FAIL |
| MAE | 15/24 | 62% | FAIL |
| MFE | 15/24 | 62% | FAIL |
| catalyst | 13/24 | 54% | FAIL |
| broker_order_id | 12/24 | 50% | FAIL |
| close_reason | 9/24 | 38% | FAIL |
| post_trade_analyzed | 4/24 | 17% | FAIL |
| hold_time_min | 2/24 | 8% | CRITICAL |

## Linkage Completeness

| Linkage | Count | Pct | Status |
|---------|-------|-----|--------|
| Thesis outcomes | 21/24 | 88% | GOOD |
| Outcome analytics | 16/24 | 67% | WARN |
| Hermes audit | 0/24 | 0% | MISSING |
| Backtest comparison | 0/24 | 0% | MISSING |
| Lesson memory | 10 total | — | LOW |

## Distance to Targets

| Target | Distance | Progress |
|--------|----------|----------|
| 2,000 usable trades | 1,976 more needed | 1.2% |
| 4,000 usable trades | 3,976 more needed | 0.6% |

## Critical Issues

1. **hold_time_min at 8%**: The hold_time computation is broken on most close paths
2. **Hermes audit at 0%**: No Hermes trade audit integration exists yet
3. **Backtest comparison at 0%**: No paper-vs-backtest comparison running
4. **pnl at 75%**: 6 closed trades missing PnL computation
5. **exit_price at 75%**: 6 closed trades missing exit price
6. **post_trade_analyzed at 17%**: Overnight LLM analysis not running consistently
7. **catalyst at 54%**: Half of trades lack catalyst documentation
8. **Sample size**: 24 closed trades — statistically meaningless. Need 83x more for P4.

## Conclusion

The system is at **Level P0 — Not Enough Data**. With 24 closed paper trades, we cannot draw any statistical conclusions about system performance. The early numbers are encouraging (profit factor 6.35, positive expectancy), but the sample is too small to be reliable.

Before scaling trade volume, the field completeness issues (especially hold_time, PnL, exit_price) must be fixed. Generating more trades with broken data pipelines will produce junk data.
