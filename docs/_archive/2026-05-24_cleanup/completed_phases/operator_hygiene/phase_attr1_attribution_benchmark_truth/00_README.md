# ATTR-1 — Attribution Benchmark Truth Layer

**Status:** COMPLETE

## Root Cause

Benchmark prices (SPY, ITA, AGG) were missing from `price_cache.json`. The `portfolio_performance_attribution.py` script tried to fetch them via yfinance, but yfinance >= 0.2.x returns MultiIndex DataFrame columns. The script's `hist["Close"].items()` returned Series objects instead of floats, causing a silent `float(price)` failure in a try/except block. No prices were cached, so all benchmark metrics were null.

## Fix

1. **yfinance MultiIndex fix** — flatten `hist["Close"]` with `iloc[:, 0]` when it returns a DataFrame
2. **Benchmark data fetched** — SPY/ITA/AGG: 1604 days each (2020-01-02 → 2026-05-20)
3. **UI truth patch** — replaced silent N/A with explicit "Unavailable" + reason banner; added bench Sharpe/Sortino/MaxDD comparison
4. **API completeness** — added `bench_sharpe`, `bench_sortino`, `bench_maxdd` to API response

## Before / After

| Metric | Before | After |
|--------|--------|-------|
| Alpha | N/A | +1.02% |
| Portfolio CAGR | 19.69% | 19.69% |
| Benchmark CAGR | N/A | 18.67% |
| Port Sharpe | 0.83 | 0.83 |
| Bench Sharpe | N/A | 1.05 |
| Port Sortino | 0.883 | 0.883 |
| Bench Sortino | N/A | 1.043 |
| Port Max DD | -17.82% | -17.82% |
| Bench Max DD | N/A | -12.5% |
| Rolling Alpha | 0 points | 24 points |
| SPY in cache | missing | 1604 days |
| ITA in cache | missing | 1604 days |
| AGG in cache | missing | 1604 days |

## Schema Decision

No new DB tables were needed. The attribution pipeline uses:
- `data/portfolios/state/price_cache.json` for benchmark and portfolio price history
- `data/portfolios/state/performance_attribution.json` as the computed output
- `data/portfolios/state/holdings.json` for current portfolio positions

Existing infrastructure was sufficient — the only issue was the yfinance column format change.

## Safety

- No fake data — all metrics computed from real 1604-day price history
- No trades, orders, or strategy changes
- Paper mode preserved
- Alpha shown only when both portfolio and benchmark CAGR are real
