# Phase 71C — Finviz Failure Dedupe Integration

Integration with Phase 68 alert dedupe:
- credential_expired:finviz:cookie → 60-min suppression window
- ingestion_failed:screener:* → group after 3 consecutive failures
- auto-skip after 3 failures, resume on next cookie update
