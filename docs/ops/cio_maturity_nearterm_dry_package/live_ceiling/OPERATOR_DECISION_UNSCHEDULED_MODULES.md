# OPERATOR_DECISION — unscheduled modules (schedule vs delete)

**Campaign:** cio-maturity-nearterm-dry-20260909 live ceiling  
**Decided_at_utc:** 2026-09-09T04:02:00Z  
**Decided_by:** operator execute full ceiling (all C items)  
**Cron grant present:** NO — install is **blocked**; this file records the decision and proposed lines only.

## Decision

| Module | Decision | Rationale |
|---|---|---|
| `cio_wave3b_report.py --json` | **SCHEDULE** (advisory, no alert) | Dry-exercised; keep as scheduled honesty surface, not silent claim |
| `cio_wave3c_report.py --json` | **SCHEDULE** (advisory, no edgar fetch beyond existing script defaults) | Same |
| `build_catalyst_graph.py --diagnose-staleness --json` | **SCHEDULE** (diagnose only; **no `--apply`**) | Staleness signal without writing projection |
| `NotificationPolicy@v1` / notification router classes | **KEEP UNSCHEDULED** pending separate design | IMMEDIATE/CC_ONLY never fire; scheduling a dark router without a producer is theatre — delete-the-claim deferred until a producer PR exists |
| `run_integrity_checks.py --json` | **ALREADY SCHEDULED** (verify only; do not duplicate) | Watchers + existing cron; no second writer |

## Proposed crontab lines (NOT INSTALLED — needs `cron` grant)

```cron
# CIO near-term honesty surfaces — advisory JSON only; no --apply / --alert
15 * * * * CUR=$(readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT) && cd "$CUR" && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_wave3b_report.py --json >>/home/johnclaw/logs/cio_wave3b_report.log 2>&1
20 * * * * CUR=$(readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT) && cd "$CUR" && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/cio_wave3c_report.py --json >>/home/johnclaw/logs/cio_wave3c_report.log 2>&1
25 * * * * CUR=$(readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT) && cd "$CUR" && /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/build_catalyst_graph.py --diagnose-staleness --json >>/home/johnclaw/logs/cio_catalyst_diagnose.log 2>&1
```

## Claim impact

- `P3_SCHEDULED` remains **AWAITING_CRON_GRANT** (decision made; install not done).
- Does **not** claim modules are scheduled in production until crontab shows the lines.
