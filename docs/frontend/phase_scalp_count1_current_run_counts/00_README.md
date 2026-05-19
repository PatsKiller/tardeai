# SCALP-COUNT-1 — Fix Live Scalp Current-Run Counts

**Status:** COMPLETE

## Root Cause

The `/api/v2/trade-ai` endpoint queried `trade_ai_scans WHERE run_date >= CURRENT_DATE - 1 day`
with `DISTINCT ON (symbol)`, returning ALL unique symbols from today + yesterday (~1418).
But the latest run only scanned 64 symbols. The GO/WAIT/NO GO cards counted ALL 1418
symbols, not the 64 from the current run.

## Fix

- API now computes `current_run_*` counts by filtering tickers to `scan_run_label = latest_run_label`
- Added fields: `current_run_scanned`, `current_run_go`, `current_run_wait`, `current_run_nogo`
- Added fields: `universe_count`, `universe_go`, `universe_wait`, `universe_nogo`
- `go_count`, `wait_count`, `avoid_count` now use current-run values (not universe)
- Frontend header shows "X scanned this run · Y universe"
- "ALL" filter tab renamed to "Universe"

## Before / After

| Card | Before | After |
|------|--------|-------|
| GO | 5 (universe) | current_run GO |
| WAIT | 26 (universe) | current_run WAIT |
| NO GO | 1387 (universe) | current_run NO GO |
| ALL | 1418 (universe) | Universe (1418) — clearly labeled |
| Header | "64 tickers scanned" but cards show 1418 | "64 scanned this run · 1418 universe" |

## Tests

10/10 + WATCH-2 16/16 regression. Frontend build clean.
