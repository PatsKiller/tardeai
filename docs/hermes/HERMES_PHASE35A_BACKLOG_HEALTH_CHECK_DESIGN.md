# Hermes Phase 35A — Backlog Health Check Design

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Script

- Name: `scripts/hermes_backlog_health_check.py`
- Type: Read-only backlog health analyzer
- DB writes: ZERO
- Backlog mutations: ZERO

## Timer/Service

- Service: `~/.config/systemd/user/hermes-backlog-health-check.service`
- Timer: `~/.config/systemd/user/hermes-backlog-health-check.timer`
- Schedule: Daily 06:45 UTC (02:45 ET) — 15 min after observation check

## Checks

| # | Check | Method |
|---|-------|--------|
| 1 | Total backlog count | SELECT COUNT |
| 2 | Open (staged) backlog count | SELECT COUNT WHERE status='staged' |
| 3 | High-priority count | evidence_json priority='high' |
| 4 | Stale backlog (>7 days unresolved) | created_at comparison |
| 5 | Duplicate-like items | topic similarity check |
| 6 | Missing owner_agent | evidence_json check |
| 7 | Missing requested_research | evidence_json check |
| 8 | Missing evidence | evidence_json empty |
| 9 | Missing symbol | symbol IS NULL |
| 10 | Source surface distribution | tags array analysis |
| 11 | Oldest/newest item | MIN/MAX created_at |
| 12 | Ready for source discovery | has URL or searxng tag |
| 13 | Operator review recommendations | Priority-sorted top 5 |

## Stale Threshold

- > 7 days since created_at with status still 'staged' = STALE

## Duplicate Heuristics

- Same symbol + same backlog_type = potential duplicate
- Check against existing backlog rows only

## Output

- `docs/hermes/backlog_health/<YYYY-MM-DD>_backlog_health_report.md`
- `docs/hermes/backlog_health/latest_backlog_health_summary.json`

## Rollback

```bash
systemctl --user stop hermes-backlog-health-check.timer
systemctl --user disable hermes-backlog-health-check.timer
```
