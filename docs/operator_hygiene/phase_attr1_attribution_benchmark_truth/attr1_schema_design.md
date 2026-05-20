# ATTR-1 Schema Design

## Decision: No New Tables Required

The attribution pipeline uses JSON files, not DB tables:

| Data | Source | Format |
|------|--------|--------|
| Benchmark prices | `price_cache.json` (SPY/ITA/AGG via yfinance) | `{symbol: {date: price}}` |
| Portfolio prices | `price_cache.json` (all held symbols) | Same format |
| Holdings | `holdings.json` | Alpaca portfolio state |
| Attribution output | `performance_attribution.json` | Computed metrics |

## Why JSON Instead of DB Tables

1. The attribution pipeline was designed and working — only the yfinance fetch was broken
2. Price cache serves multiple consumers (attribution, performance history, portfolio repricing)
3. Adding DB tables would duplicate data already in the JSON cache
4. The attribution computation runs as a batch job, not a query-time calculation

## Future Enhancement (Not Required Now)

If real-time attribution or historical time-series is needed:
- `attribution_daily_snapshots(date, portfolio_return, benchmark_return, alpha, sharpe)`
- Would be populated by a cron job reading from the same price cache

This was deferred because the current pipeline produces correct metrics from 498 days of data.
