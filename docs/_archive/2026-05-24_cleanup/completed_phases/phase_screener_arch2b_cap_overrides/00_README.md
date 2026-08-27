# SCREENER-ARCH-2B — Broad Screener Cap Overrides

**Status:** COMPLETE

## Fix

Per-screener cap overrides for 4 broad ETF/income screeners that exceeded 5,000:

| Screener | Old Cap | New Cap | Actual Rows | Status |
|----------|---------|---------|-------------|--------|
| bond_etf_income | 5,000 | **10,000** | 5,230 | **EXHAUSTED** |
| covered_call_etf | 5,000 | **10,000** | 5,230 | **EXHAUSTED** |
| high_yield_income | 5,000 | **10,000** | 6,367 | **EXHAUSTED** |
| ira_income_friendly | 5,000 | **10,000** | 6,367 | **EXHAUSTED** |

**Zero data loss.** All 4 screeners now fully exhaust their result sets.

## Design

- Global default: `DEFAULT_MAX_ROWS = 5000`
- Per-screener overrides in `SCREENER_CAP_OVERRIDES` dict
- Cap status tracked: `EXHAUSTED` vs `ROW_LIMIT_REACHED`
- `raw_fetched` and `effective_cap` recorded per screener run

## Tests

7/7 + ARCH-2 13/13 regression.
