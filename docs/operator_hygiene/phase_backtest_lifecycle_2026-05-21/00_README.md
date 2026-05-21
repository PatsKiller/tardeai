# Backtest Lifecycle Full Fix (2026-05-21)

## What operator saw: all zeros on /v2/backtesting

## Root causes:
1. Overview tiles read from paginated array lengths, not status API (showed 0 despite 33 runs)
2. strategy_backtest_results was empty — aggregation never ran after backtest runs completed
3. No missed opportunities view existed
4. Results API queried wrong columns (old schema vs new)
5. No "Missed" tab for rejected/expired proposals

## Fixes:
1. **Overview tiles** read from `/api/v2/backtesting/status` — shows 33 runs, 872 trades
2. **Results aggregator** (`backtest_results_aggregator.py`) computed win_rate, PF, equity curve, drawdown for all 33 runs
3. **Missed opportunities** API + "Missed" tab: 50 proposals that expired/rejected, 31 would have won, $41.57 left on table
4. **Results API** updated to return all new fields (run_type, total_pnl, equity_curve, drawdown)
5. **Tooltip** on "SIMULATED EVIDENCE ONLY" explaining what backtests can/cannot tell you
6. **Tab counts** show real numbers from status API

## Strategy Performance (from backtest results):
See Results tab on /v2/backtesting for per-run win rates, profit factors, and P&L.
