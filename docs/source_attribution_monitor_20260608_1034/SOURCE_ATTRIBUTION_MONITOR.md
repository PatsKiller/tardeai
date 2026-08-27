# Source Attribution Monitor (2026-06-08)
Tracks the news↔trade overlap + attribution coverage over time so the source-maturity + calibration loops
are observably strengthening (and a stall is caught).

- `scripts/source_attribution_monitor.py` (daily cron `0 6 * * *`, read-only): snapshots traded_30d,
  traded_with_news_7d (overlap_pct), source_rows, sources_with_trades, sources_outcome_proven,
  total_attributions → appends to data/runtime/source_attribution_history.json (last 90), with deltas + status.
- **Status logic:** HEALTHY (overlap ≥70%); DEGRADED (<70%); REGRESSED (dropped >20pts vs prior);
  **STALLED** (overlap healthy ≥5 days but still 0 attributions → attribution loop needs a look).
- Baseline today: overlap **84.2%** (16/19), attributions 0 (forward-looking ramp), status HEALTHY, streak 1d.
- v3: `/api/v2/hermes/source-maturity` → `attribution_health` (status, overlap%, attributions, 14-day trend);
  System→Hermes "Source Maturity" card shows the overlap%/attributions/status line.
- As trades occur on now-news-covered symbols, total_attributions + sources_with_trades climb from 0; the
  trend makes the strengthening visible. Read-only; no trades/scoring change.
