# Hermes Phase 34A — Observation Automation Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Script

- Name: `scripts/hermes_observation_check.py`
- Type: Read-only health/status checker
- DB writes: ZERO
- Alerts: NONE
- External queries: NONE

## Timer/Service

- Service: `~/.config/systemd/user/hermes-observation-check.service`
- Timer: `~/.config/systemd/user/hermes-observation-check.timer`
- Schedule: Daily 06:30 UTC (02:30 ET) — after Hermes 01:00 UTC loop
- User: johnclaw (systemd user unit)

## Checks Performed

| # | Check | Method | Write? |
|---|-------|--------|--------|
| 1 | Hermes gateway status | systemctl --user is-active | NO |
| 2 | Hermes autonomous loop timer | systemctl --user is-active | NO |
| 3 | Hermes last loop log | journalctl --user tail | NO |
| 4 | SearXNG container status | docker ps | NO |
| 5 | SearXNG endpoint | curl 127.0.0.1:18888 | NO |
| 6 | Research backlog count | SELECT COUNT (read-only) | NO |
| 7 | Hermes staged/promoted counts | SELECT COUNT (read-only) | NO |
| 8 | Hermes embeddings count | SELECT COUNT (read-only) | NO |
| 9 | Kill switch state | File exists check | NO |
| 10 | Safe view availability | SELECT 1 FROM view LIMIT 1 | NO |
| 11 | Dashboard endpoint | curl 127.0.0.1:7777 health | NO |
| 12 | Cron job count | crontab -l wc -l | NO |

## Output

- `docs/hermes/observations/<YYYY-MM-DD>_observation_report.md`
- `docs/hermes/observations/latest_observation_summary.json`

## No-Write Policy

The script MUST NOT:
- Write to any DB table
- Send Telegram/email alerts
- Modify systemd services or timers
- Start/stop Docker containers
- Query SearXNG search endpoints
- Create embeddings or promotions
- Call external APIs

## Kill Switch

If `hermes_sidecar/.hermes/DISABLED` exists, the observation script still runs but reports "kill switch ACTIVE" in the report.

## Rollback/Disable

```bash
systemctl --user stop hermes-observation-check.timer
systemctl --user disable hermes-observation-check.timer
```
