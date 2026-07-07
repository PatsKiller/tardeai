# Profit-Capture All-Trades Analysis

Generated: 2026-06-27T01:51:43.701934+00:00

**Advisory / analytics only. No broker, order, stop, proposal, GO/WAIT or strategy changes.**

## Summary

- **total_closed_trades**: 196
- **measurable_closed_trades**: 34
- **winners**: 130
- **winners_with_mfe**: 13
- **winners_with_giveback**: 9
- **winners_protection_missed**: 5
- **winners_advisory_existed**: 2
- **winners_operator_acted**: 0
- **money_left_total**: 1239.29

## Money left by strategy

- momentum_scalp: $817.08
- swing_breakout: $217.99
- fib_retracement_bounce: $102.55
- screener: $89.7
- dividend_growth_compounder: $11.97

## Money left by source system

- alpaca_paper: $1239.29

## Failure-class breakdown

- DATA_INCOMPLETE: 117
- NOT_PROTECTABLE: 74
- NO_ADVISORY_GENERATED: 5

## Data-quality breakdown

- ok: 45
- bar_mfe: 34
- no_bars: 117

## Protectable winners that missed protection

| sym | source | strat | realized | max$ | giveback$ | gb% | advisory | failure |
|-----|--------|-------|----------|------|-----------|-----|----------|---------|
| ANY | alpaca_paper | momentum_scalp | 309.5 | 841.84 | 532.34 | 63.2 | False | NO_ADVISORY_GENERATED |
| ANY | alpaca_paper | momentum_scalp | 315.69 | 600.43 | 284.74 | 47.4 | False | NO_ADVISORY_GENERATED |
| APPS | alpaca_paper | swing_breakout | 159.98 | 334.0 | 141.68 | 42.4 | False | NO_ADVISORY_GENERATED |
| EVC | alpaca_paper | screener | 202.8 | 292.5 | 89.7 | 30.7 | False | NO_ADVISORY_GENERATED |
| INFU | alpaca_paper | swing_breakout | 67.83 | 114.24 | 46.41 | 40.6 | False | NO_ADVISORY_GENERATED |

## By-Ticker aggregate view (2026-07-07, PR #130)

The Journal aggregated by day / strategy / account / session / setup but **never by symbol**. New
**By Ticker** tab + `GET /api/v2/journal/by-ticker[?symbol=&from=&to=&account=]` — per-symbol realized
rollup over `trade_closed`: #trades, win rate, total/avg P&L, avg P&L %, **avg hold**, best/worst,
**profit factor**, first/last close. Account + date-range filterable (honors the Journal's existing
selectors; no account = all-accounts aggregate). `?symbol=` adds per-strategy & per-account splits + the
individual trades. Component `apps/command-center-v3/src/components/tradeinview/ByTickerPanel.tsx`.
Aggregates realized closed trades; a symbol with no closed trades shows an empty-state with an ingest hint.
