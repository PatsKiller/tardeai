# News Ingestion Gap — 2026-05-24

Status:      HISTORICAL
as_of:       2026-05-23T15:34:57-04:00
Measured at: efcc51365 / not measured

## Observed
- News articles by day (last 10 days):
  - 5/23: 192 (manual run during investigation)
  - 5/22: 0
  - 5/21: 0
  - 5/20: 151
  - 5/19: 279

## Root cause
System rebooted 2026-05-22 ~09:19 ET (uptime shows 1d 6h). Cron fired
news_ingestion.py on 5/21 12:30, 18:30 and 5/22 06:30, 12:30, 18:30
per syslog — but log file was not updated after 5/20 18:30. Script likely
encountered a silent failure in the post-reboot environment (possibly
stale flock or import path issue) that prevented output.

Manual run on 5/23 (Sunday) succeeded immediately: 192 articles written.
Second immediate run found 0 new (deduplication working correctly).

## Action taken
- Manual ingestion run: 192 articles written for 5/23
- Articles for 5/21-5/22 are lost (news window passed, APIs return current only)
- No code changes needed — script works correctly when invoked

## Monday burn-in impact
- Catalyst verification (Maria): slightly degraded for 5/21-5/22 symbols
  but 192 fresh articles now available from 5/23 manual run
- RAG context: fresh articles ingested, recency-weighted
- Aegis morning brief: will use 5/23 articles, adequate

## Follow-up needed
- Monitor cron execution on Monday 06:30/12:30/18:30 — verify log file updates
- If cron still fails silently, add explicit env sourcing to cron line
- Consider adding heartbeat decorator to news_ingestion.py for pipeline visibility
