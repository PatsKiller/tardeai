# Phase 71C — Finviz Failure Dedupe Integration

Status:      HISTORICAL
as_of:       2026-06-01T11:55:37-04:00
Measured at: efcc51365 / not measured

Integration with Phase 68 alert dedupe:
- credential_expired:finviz:cookie → 60-min suppression window
- ingestion_failed:screener:* → group after 3 consecutive failures
- auto-skip after 3 failures, resume on next cookie update
