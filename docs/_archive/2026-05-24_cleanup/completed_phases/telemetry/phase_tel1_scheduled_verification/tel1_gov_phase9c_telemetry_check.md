# TEL-1 — GOV-1 / Phase 9C Telemetry Check

## Result: PARTIAL — Jobs ran but hit flock lock

| Job | Time | Log Status | Telemetry |
|-----|------|-----------|-----------|
| System Facts (07:40) | 07:40 | Locked, skipping | No row — flock not acquired |
| A1A Check (07:45) | 07:45 | Locked, skipping | No row — flock not acquired |
| Maturity Board (07:55) | 07:55 | Locked, skipping | No row — flock not acquired |

## Root Cause

All 3 GOV-1/Phase 9C jobs hit "Locked, skipping" — another process held the flock, or the lock file was stale from a previous run. The telemetry call is placed AFTER the main work, so when the wrapper skips due to flock, telemetry is never reached.

## Fix Applied

Commit `aa083ac` patched all 3 wrappers to record `skipped` with `source='cron_flock_blocked'` at the flock exit point. Next time they hit a lock (tomorrow 07:40-07:55), a "skipped" telemetry row will appear in pipeline_runs instead of silence.
