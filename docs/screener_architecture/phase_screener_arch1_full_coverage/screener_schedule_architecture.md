# SCREENER-ARCH-1 Schedule Architecture

## Critical Fix

**50-row hard cap removed.** `finviz_screener_runner.py` line 79 had `tickers[:50]` which
artificially truncated results. Finviz export returns ALL matching rows in a single CSV.
Cap raised to 500 per screener.

## Root Cause of 65 Symbols

- Only 2 cron runs exist for the main screener: 10 AM and 4 PM
- The 0900 runs come from a separate pipeline (finviz_ingestion), not the main runner
- The 50-row cap per screener meant 27 screeners x 50 max = 1350 theoretical max, but only a subset of screeners fire at each time slot
- After the fix: each screener can return up to 500 rows

## Schedule Design

| Session | Time ET | Purpose | Screeners |
|---------|---------|---------|-----------|
| After-close | 16:15 | Position/swing/dividend/growth | Long-term, mean reversion |
| Overnight | 20:00 | Fundamentals refresh, news, catalysts | All passive |
| Premarket | 04:30 | Gap/momentum premarket movers | Momentum, gap |
| Market open | 09:00 | Active intraday/scalp | Momentum, scalp, catalyst |
| Intraday | 10:30, 12:00, 14:00, 15:30 | Refresh momentum, trend | Active strategies |
| Weekly | Sunday 18:00 | Long-term universe refresh | ETF, sector, portfolio |

## Existing Cron

- 10 AM: finviz_screener_runner.py --run
- 4 PM: finviz_screener_runner.py --run
- Various: finviz_ingestion runs at multiple slots

## Impact

With the 50→500 cap fix, the next screener run should return significantly more symbols.
The existing 10 AM and 4 PM schedule is adequate for now — the cap was the bottleneck.
