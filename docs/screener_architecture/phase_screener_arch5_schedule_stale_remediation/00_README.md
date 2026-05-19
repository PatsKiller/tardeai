# SCREENER-ARCH-5 — Schedule and Stale Screener Remediation

**Status:** COMPLETE

## What Was Delivered

1. **Schedule baseline**: 27 active screeners across 5 session types (intraday, after_close, weekly, biweekly, monthly). 0 stale, 0 orphaned.

2. **Schedule config** (`config/screener_schedule.yaml`): Session definitions, stale thresholds, alert policy.

3. **Stale detection + remediation** (`scripts/remediate_stale_screeners_arch5.py`): Schedule-aware freshness checks. Dry-run showed 0 stale screeners.

4. **Health alert** (`scripts/send_screener_schedule_health_alert.py`): Routes through OPS-HYGIENE-1 router. P0 only if 3+ daily screeners stale. P1 for routine. P3 for success.

5. **API endpoint**: GET /api/v2/screener-schedule/summary

6. **Coverage assessment**: 7x/day screener runs (07:00-18:00), 4x/day orchestrator. No new cron needed. Two minor gaps: no dedicated premarket (<07:00) or overnight (>18:00) session — acceptable for paper phase.

## Tests

16/16 pass.
