# SCREENER-ARCH-2 Full Ingestion Results

## Live Run After Server Restart

| Metric | Old (50 cap) | ARCH-1 (500) | ARCH-2 (full) |
|--------|-------------|--------------|---------------|
| Total rows | ~1,350 | ~8,842 | **~41,000** |
| New tickers | ~5 | 259 | **2,973** |
| Screeners capped | 25/27 | 14/27 | **4/27** |
| Screeners exhausted | 2/27 | 13/27 | **23/27** |

## Capped Screeners (Hit 5,000 Emergency Cap)

| Screener | Available | Capped At | Missed |
|----------|-----------|-----------|--------|
| bond_etf_income | 5,230 | 5,000 | 230 |
| covered_call_etf | 5,230 | 5,000 | 230 |
| high_yield_income | 6,367 | 5,000 | 1,367 |
| ira_income_friendly | 6,367 | 5,000 | 1,367 |

Total missed due to 5,000 cap: ~3,194 rows across 4 broad ETF/income screeners.

## Fix Applied

- `tickers[:50]` removed (was discarding 95%+ of results)
- `tickers[:500]` removed (was discarding ~50% on large screeners)
- Now returns full CSV result set
- Emergency cap at 5,000 prevents memory issues
- New ticker incubator insertion raised from 10 to 200 per screener
