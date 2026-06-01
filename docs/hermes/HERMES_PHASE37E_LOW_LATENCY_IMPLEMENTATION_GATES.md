# Hermes Phase 37E — Low-Latency Bridge Implementation Gates

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Future Phases

### Phase 44A — Event Queue Schema Design

- Design hermes_advisory_events table
- No DB changes
- Docs only

### Phase 44B — Event Queue Table Creation

- CREATE TABLE hermes_advisory_events
- GRANT SELECT/INSERT to hermes_staging_writer
- Rollback SQL
- Caps: 1 table, no triggers yet

### Phase 44C — Manual Event Insert Dry-Run

- Manually INSERT test event
- Verify schema works
- No worker, no trigger
- Rollback: DELETE test event

### Phase 44D — Bridge Worker Dry-Run

- Create bridge worker script
- Run manually in dry-run mode
- Read events, log actions, no cache writes
- File output only

### Phase 44E — Worker Apply to Advisory Cache

- Worker refreshes llm_intelligence_cache for existing promoted sections
- Max 2 refreshes per dry-run
- Operator approval required
- Rollback: revert cache rows

### Phase 44F — Dashboard Queue Visibility

- Read-only queue depth/status on dashboard
- GET endpoint only
- No action buttons

### Phase 45 — Fallback Timer

- Systemd timer every 5 min
- Processes missed events if worker is down
- Read-only fallback, same safety rules

### Phase 46 — Cron Polling Reduction

- Identify cron jobs that can be replaced by event-driven bridge
- Reduce polling frequency for replaced jobs
- Per-job approval required

---

## Each Phase Requires

- Caps on writes
- Rollback plan
- No-execution boundary (no trade/proposal/journal/holdings)
- Latency measurement
- Operator approval
- Kill switch
- Dashboard visibility
