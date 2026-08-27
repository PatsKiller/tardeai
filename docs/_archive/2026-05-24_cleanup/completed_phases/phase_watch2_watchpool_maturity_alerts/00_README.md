# WATCH-2 — Watchpool Maturity Alerts and No-Leads Diagnostic

**Status:** COMPLETE

## Purpose

Bridges the gap between watchpool/incubator candidates and operator alerts.
When 79 incubator candidates exist but 0 proposals, the system now explains why.

## Key Findings

| Metric | Value |
|--------|-------|
| No-leads root cause | system_quiet_but_explained |
| Candidates reviewed | 200 |
| Needs quote refresh | 98 |
| Maturing | 69 |
| Stale/expired | 31 |
| Near trigger | 1 |
| Alerts required | 200 |

## Scripts

- `watchpool_maturity_policy.py` — Maturity classification (14 states)
- `report_no_leads_root_cause.py` — Explains why no actionable leads
- `report_watchpool_maturity_audit.py` — Full maturity audit
- `send_watchpool_maturity_alerts.py` — Telegram maturity alerts
- `send_no_leads_diagnostic_alert.py` — Telegram no-leads diagnostic
- `run_scheduled_watchpool_alerts.sh` — Cron wrapper
- `rollback_watch2_watchpool_alert_cron.sh` — Rollback

## Cron

| Time | Mode |
|------|------|
| 09:35 M-F | maturity |
| 10:05 M-F | maturity |
| 11:30 M-F | diagnostic |
| 13:30 M-F | maturity |
| 15:30 M-F | maturity |

## Tests

16/16 WATCH-2 + ALERT-3 14/14 + Q-1 20/20 regression.
