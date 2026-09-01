# Phase 207J — v3 Daily Cadence Visibility — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:11:11-04:00
Measured at: efcc51365 / not measured

## Finding
No existing endpoint consumed the `portfolio_maintenance_*_last_run.json` cadence summaries, so v3 could
not surface the migration status. Added a **read-only** endpoint so v3 can consume it:
`GET /api/v2/system/portfolio-cadence-status` (`_portfolio_cadence_status`). Also corrected the stale
`portfolio_maintenance: not_migrated` field in `/api/v2/system/governance-pipeline-status` to
`partial_migrated` (backup migrated, daily pilot).

## Endpoint surfaces (verified live)
- **daily portfolio cadence:** `status=pilot_scheduled_parallel`; last run 2026-06-07T15:06:52Z,
  `dry_run=false`, `overall=ok`, label `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY` (`review_only=true`).
- **last run / next run:** daily cadence timer `active/enabled`, next-elapse exposed.
- **advisory-draft review-only label:** YES.
- **backup cadence already migrated:** `backup.status=migrated`, timer active/enabled, `legacy_retired=true`.
- **weekly/monthly/lookthrough not migrated:** `not_migrated: [weekly, monthly, lookthrough, db_retention, price_cache]`.
- **retired legacy daily count:** 0; **active legacy daily count:** 1 (`legacy_timer portfolio-daily.timer`
  active/enabled — parallel observation).
- **safety badges:** `paper_only=true, live_trading=false, level7=prohibited, destructive_excluded=[db_retention,
  price_cache], safety_net_watchdog=untouched`.

## Scope note
The data is now **consumable** by v3 (read-only endpoint). A v3 Queue/Control-Plane card to render it is a
small, optional follow-up — **not built here** to keep this pilot backend-only and low-risk. **No v2 UI**
was changed. The systemctl timer reads inject `XDG_RUNTIME_DIR` so they resolve from the server process.
