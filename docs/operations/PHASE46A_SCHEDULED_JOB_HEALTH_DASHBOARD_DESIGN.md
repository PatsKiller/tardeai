# Phase 46A — Scheduled Job Health Dashboard Design

**Date:** 2026-06-01
**Status:** COMPLETE

## Dashboard Section

- Page: System Applications or dedicated System Health
- Section: "Scheduled Jobs"
- Type: Read-only

## API

- Endpoint: `GET /api/v2/system/scheduled-jobs`
- Returns: timer statuses, cron count, active/failed/waiting

## Fields

| Field | Source |
|-------|--------|
| Active systemd timers | systemctl --user list-timers |
| Timer count | count |
| Active cron jobs | crontab -l count |
| Hermes timers | filter hermes-* |
| Trade AI timers | filter tradeai-* |
| Last observation report | latest_observation_summary.json |
| Last backlog health | latest_backlog_health_summary.json |

## No Controls

- No start/stop buttons
- No retry buttons
- No cron edit
- Read-only status display only
