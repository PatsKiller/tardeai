# SCREENER-ARCH-1 — Full Screener Coverage

**Status:** COMPLETE

## Critical Fix

**50-row hard cap removed.** `finviz_screener_runner.py` line 79 had `tickers[:50]`
which artificially truncated ALL screener results to 50 rows. Finviz export returns
all matching rows in a single CSV — the truncation was Python-side, not API-side.

**Cap raised to 500 per screener.**

## Root Cause of 65 Symbols

1. **50-row cap** — each screener was limited to 50 results regardless of how many Finviz returned
2. **Subset scheduling** — only a few screeners fire at 0900; the full set runs at 1000/1600
3. **8 stale screeners** — not firing despite active=true

## Inventory Findings

| Metric | Value |
|--------|-------|
| Total screeners | 27 |
| Active | 27 |
| Stale (>3 days) | 8 |
| Returning exactly 50 | 25 |
| Returning < 50 | 2 |

## Expected Impact

Next screener run should return significantly more symbols per screener (up to 500).
With 27 screeners x avg ~100-200 rows each (after dedup), universe should grow substantially.

## Stale Screeners Needing Attention

| Screener | Last Run | Strategy |
|----------|----------|----------|
| Bond ETF Income | May 8 | bond_income |
| Core Index / Broad Market | May 8 | core_index |
| Dividend Aristocrats (Growth) | May 13 | dividend_growth |
| High-Yield Income (BDC/CEF) | Apr 29 | high_yield |
| International Dividend | May 7 | international |
| IRA-Friendly Income | May 14 | high_yield |
| REIT Income Scanner | May 8 | reit |
| Roth-Friendly Growth | May 8 | core_growth |
| Taxable-Friendly Qualified Dividends | May 7 | dividend |
| Value + Income | May 11 | dividend |

These need schedule investigation (SCREENER-ARCH-2).

## Tests

6/6 + WATCH-2 16/16 regression.
