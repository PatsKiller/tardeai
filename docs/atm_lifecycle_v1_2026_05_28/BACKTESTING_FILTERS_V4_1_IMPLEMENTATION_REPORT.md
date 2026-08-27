# Backtesting Filters v4.1 Implementation Report

**Date:** 2026-05-28

## Summary
Made backtesting page filters fully data-driven and functional. Replaced cosmetic broker/account
dropdowns with strategy and run-type filters sourced from actual backtest data. All API endpoints
accept filter parameters and return filtered results server-side.

## Files Changed
- `scripts/api_v2.py` — 6 endpoints updated with filter params
- `apps/command-center-v2/src/pages/Backtesting.tsx` — full rewrite of filter logic

## Endpoints Changed
| Endpoint | Filter Params Added |
|----------|-------------------|
| `/api/v2/backtesting/status` | strategy, start_date, end_date, run_id |
| `/api/v2/backtesting/runs` | strategy, start_date, end_date, run_id, run_type, limit |
| `/api/v2/backtesting/results` | strategy, run_id, run_type, limit |
| `/api/v2/backtesting/trades` | strategy, start_date, end_date, run_id, symbol, limit |
| `/api/v2/backtesting/filter-options` | Now returns strategies, run_ids, run_types, data_quality_gaps |

## Filter Contract

### Available filters (from `/filter-options`)
```json
{
  "strategies": ["all_signals", "bond_income", "core_growth_compounder", ...],
  "run_ids": ["run_20260521_...", ...],
  "run_types": ["replay_trades", "replay_proposals", "champion"],
  "brokers": ["alpaca", "schwab", ...],
  "accounts": ["alpaca_paper", "schwab_roth_ira", ...],
  "minDate": "2026-05-06",
  "maxDate": "2026-05-27",
  "data_quality_gaps": [
    "strategy_backtest_trades has no broker/account columns — broker/account filters apply to trail/MFE only"
  ]
}
```

### Implemented filters
| Filter | Data-Driven | Affects |
|--------|------------|---------|
| Start date | Yes (minDate/maxDate from signal_time) | trades, runs, status counts |
| End date | Yes | trades, runs, status counts |
| Strategy | Yes (from DISTINCT strategy_id) | trades, runs, results, status counts |
| Run type | Yes (from DISTINCT run_type) | runs, results |

### Why broker/account were replaced
`strategy_backtest_trades` has no `broker` or `account` columns. The old broker/account
dropdowns were populated from `paper_trades` but applied to backtest data where those
fields don't exist. They were replaced with strategy and run-type filters that match
actual data.

## Tabs Filtered
| Tab | Filtered | Method |
|-----|----------|--------|
| Overview | Yes | Charts computed from server-filtered trades |
| Strategy | Yes | Strategy stats from server-filtered trades |
| Trades | Yes | Server-side WHERE clause + limit 5000 |
| Missed | Partially | Not date-filtered (proposals, not backtest trades) |
| Results | Yes | Server-side strategy + run_type filter |
| Runs | Yes | Server-side all filters |
| Trail Analysis | No | paper_trades-based, no backtest date column |
| MFE/MAE | No | paper_trades-based |
| Optimization | No | Derived from MFE data |

## Frontend Changes
- Filters refetch all data on change (server-side, not client-side)
- Strategy dropdown populated from API `filter-options.strategies`
- Run type dropdown populated from API `filter-options.run_types`
- Date inputs bounded by min/max from data
- Filtered count shown: "Showing 472 of 2,568 trades"
- KPI cards show filtered/total when filters active
- Clear button resets all filters
- Data quality warnings shown when filters active
- Empty state for no-match scenarios
- Trades table now shows Date column (from signal_time)
- Trades limit raised from 50 to 5,000

## Data Quality Gaps
- `entry_time` is NULL for all 2,568 backtest trades — `signal_time` used instead
- `strategy_backtest_trades` has no broker/account columns
- Trail analysis and MFE/MAE are paper_trades-based and don't filter by backtest params

## Validation
- SQL verified: strategy filter → 4 earnings_catalyst, date filter → 472 since May 21
- Build: PASS (395ms)
- API server caches module — changes visible after server restart

## Safety
- No orders placed
- No broker writes
- No paper_trades trade-state changes
- No proposal changes
- No journal mutations
- No backtest result mutations
- No LLM calls
- No Grok calls
- No cron changes
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true

## Rollback
```bash
git revert <commit_hash>
cd apps/command-center-v2 && npx vite build
```
