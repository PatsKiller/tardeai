# Phase 181C: Current Paper Trade Loop Validation Report

Status:      HISTORICAL
as_of:       2026-06-01T23:29:18-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Mode**: PAPER ONLY

## Summary

| Metric | Value |
|--------|-------|
| Trades scanned | 24 |
| Fully closed-loop | 0 (0%) |
| Partially closed-loop | 20 (83%) |
| Broken loop | 4 (17%) |
| Loop completeness | 0% |

**No trades are fully closed-loop.** Every trade is missing at least Hermes audit and backtest comparison.

## Missing Fields (24 closed trades)

| Field | Missing | Pct Missing | Status |
|-------|---------|-------------|--------|
| hermes_audit | 24/24 | 100% | NOT IMPLEMENTED |
| backtest_quality | 24/24 | 100% | NOT IMPLEMENTED |
| hold_time | 22/24 | 92% | BROKEN |
| post_analysis | 20/24 | 83% | LAGGING |
| catalyst | 11/24 | 46% | PARTIAL |
| thesis_outcome | 9/24 | 38% | PARTIAL |
| outcome_analytics | 9/24 | 38% | PARTIAL |
| r_multiple | 8/24 | 33% | PARTIAL |
| pnl | 6/24 | 25% | PARTIAL |
| exit_price | 6/24 | 25% | PARTIAL |
| learning_linkage | 3/24 | 12% | GOOD |
| exit_reason | 0/24 | 0% | COMPLETE |

## Broken Trades (Score < 50)

| Trade | Symbol | Strategy | Score | Key Missing |
|-------|--------|----------|-------|-------------|
| #30 | AGNC | reit_income | 43.3 | pnl, exit_price, r_multiple, hold_time |
| #37 | BLMN | swing_trade | 36.7 | pnl, exit_price, r_multiple, hold_time |
| #41 | ONDS | swing_breakout | 36.7 | pnl, exit_price, r_multiple, hold_time |
| #46 | TMHC | swing_breakout | 36.7 | pnl, exit_price, r_multiple, hold_time |

## Top Issues to Fix

1. **Hermes trade audit**: Not implemented. Need Hermes to analyze each closed trade.
2. **Backtest comparison**: Not linked. Need paper trades compared against strategy backtest data.
3. **hold_time_min**: 92% missing. Most close paths skip this computation. Need fix in:
   - `paper_trade_monitor.py` integrity_check path
   - `alpaca_paper_adapter.py` sync_positions close path
   - `paper_trade_closer.py` close path
4. **Post-exit analysis**: 83% missing. Overnight LLM analysis not processing most trades.
5. **PnL/exit_price**: 25% missing. Some close paths (phantom, expired) don't compute PnL.

## Recommendations

1. Fix hold_time_min computation in ALL close paths (P0 priority)
2. Fix pnl/exit_price computation for phantom/expired closes
3. Implement Hermes post-trade audit cron
4. Add backtest comparison linkage for closed trades
5. Ensure overnight LLM analysis processes ALL unanalyzed closed trades
