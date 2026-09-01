# Code Fix Verification Matrix (2026-05-24)

Status:      HISTORICAL
as_of:       2026-05-24T10:35:08-04:00
Measured at: efcc51365 / not measured

All 11 claimed fixes verified against live source code AND live API responses.

| # | Claimed Fix | Code Verified | API Verified | Result |
|---|-------------|---------------|--------------|--------|
| 1 | Pipeline never-run not green | api_v2.py:14658 — no `green` assignment in `last_run_at is None` block | /api/v2/pipeline-health-master returns 0/31 healthy on weekend | CONFIRMED |
| 2 | Freshness checker covers all products | 16 products checked via `check()` calls | Script runs, produces PASS/WARN/FAIL | CONFIRMED |
| 3 | System health includes freshness | api_v2.py `_system_health_dashboard()` has `data_freshness` | Returns "0/5 fresh, 5 stale" with per-product detail | CONFIRMED |
| 4 | Alerts include synthetic stale alerts | `_generate_stale_data_alerts()` injects when no filter | Returns 3 system alerts (2 stale + 1 backlog) | CONFIRMED |
| 5 | Research-topics cross-refs topic_monitor | Endpoint returns `topic_monitor_count: 17` + note | Verified via curl | CONFIRMED |
| 6 | Agent calibration insufficient sample | `insufficient_sample` flag added | Returns `has_data: true, insufficient_sample: false` (has data) | CONFIRMED |
| 7 | WebSocket HTTP probe | ScalpLiveFeed.tsx: `async function tryWs()` with fetch probe | Frontend build clean | CONFIRMED |
| 8 | Rebalance income not $0 | `computed_values` with `income_current` from dividend_calendar.json | Returns `$14,408` | CONFIRMED |
| 9 | Portfolio snapshot labels | `snapshot_source` on command/rebalance/retirement | All 3 endpoints return labels | CONFIRMED |
| 10 | CIO dedup | `DISTINCT ON (symbol)` in `_cio_decisions_enriched()` | 50 decisions, 0 duplicates, V appears once | CONFIRMED |
| 11 | AI Analyst stale flag | `is_stale` computed from `generated_at` age | Returns `is_stale: true` (generated 2 days ago) | CONFIRMED |
