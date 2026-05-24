# UI-CONTRACT-1 — Live Page API/UI Contract Fixes

**Status:** COMPLETE

## Fixes Applied

1. **Self-Improvement** (commit 53051af): Fixed double-unwrap of useApi envelope. Holdings now $1.19M, all KPI tiles populate.

2. **Risk Regime** (commit 53051af): Fixed same double-unwrap. Shows "high_volatility" instead of "No regime snapshot." Indicators/signals/profiles/alignments tabs fixed.

3. **AI Analyst stale brief**: Reports tab now shows STALE badge (red) when brief is >24h old. April 2025 brief will be clearly labeled stale.

4. **Retirement rotation labels**: Non-held tickers (shares=0) now show "NOT HELD — RESEARCH ONLY" badge and "0 — not held" in shares field instead of misleading "0.0 shares → cash."

## Root Cause

All self-improvement + risk-regime bugs: `useApi` hook unwraps `{ok, data}` envelope, then pages read `.data` again = undefined.

## Morning Brief Diagnosis

No `morning_briefs` table exists in DB. The stale April 2025 content comes from a different data source — separate generator fix needed.

## Risk Regime Cron

Snapshot is 9 days stale. Classifier cron exists at 06:30/16:05 (`market_regime_collector.py` + `market_regime_classifier.py`). Separate investigation needed for why snapshot stopped updating May 11.
