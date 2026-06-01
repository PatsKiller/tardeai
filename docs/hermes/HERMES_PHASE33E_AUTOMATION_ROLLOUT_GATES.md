# Hermes Phase 33E — Automation Rollout Gates

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Future Automation Phases

### Phase 34 — Observation Automation

| Field | Value |
|-------|-------|
| Purpose | Automated daily observation audit + SearXNG health check |
| Scheduler | systemd user timer |
| Allowed writes | NONE (file output only) |
| Forbidden | Any DB write, any mutation |
| Caps | N/A (read-only) |
| Rollback | Disable timer |
| Kill switch | DISABLED file |
| Dashboard | Observation status card |
| Operator review | Daily log check |

### Phase 35 — Research Backlog Health Check

| Field | Value |
|-------|-------|
| Purpose | Daily scan for stale backlog items (>7 days unresolved) |
| Scheduler | systemd user timer |
| Allowed writes | NONE (file output + optional Telegram alert) |
| Forbidden | DB writes, backlog modification |
| Caps | N/A (observation) |
| Rollback | Disable timer |
| Kill switch | DISABLED file |
| Dashboard | Backlog staleness indicator |

### Phase 36 — Scheduled Librarian Dry-Run

| Field | Value |
|-------|-------|
| Purpose | Daily expanded Librarian analysis over safe views |
| Scheduler | systemd user timer |
| Allowed writes | NONE (file output only) |
| Forbidden | DB writes, embeddings, promotions |
| Caps | 25 findings max |
| Rollback | Disable timer |
| Kill switch | DISABLED file |
| Dashboard | Librarian findings count |

### Phase 37 — Scheduled Source-Discovery Dry-Run

| Field | Value |
|-------|-------|
| Purpose | Daily SearXNG queries from top backlog item |
| Scheduler | systemd user timer |
| Allowed writes | NONE (file output only) |
| Forbidden | DB writes, ingestion, embeddings |
| Caps | 5 queries/day, 15 results/query |
| Rollback | Disable timer |
| Kill switch | DISABLED file |
| Dashboard | Discovery count |

### Phase 38 — Scheduled Staged Research Write

| Field | Value |
|-------|-------|
| Purpose | Auto-stage source discovery candidates |
| Scheduler | systemd user timer |
| Allowed writes | hermes_research_intelligence (staged only) |
| Forbidden | Production writes, embeddings, promotions |
| Caps | 2 rows/day |
| Rollback | DELETE by run_id |
| Kill switch | DISABLED file |
| Dashboard | Staged count, source |
| Operator review | Daily review of new staged rows |

### Phase 39 — Embedding/Promotion Review Automation

| Field | Value |
|-------|-------|
| Purpose | Weekly embedding + promotion candidate recommendations |
| Scheduler | systemd user timer (weekly) |
| Allowed writes | NONE (recommendation files only) |
| Forbidden | Actual embedding, actual promotion without operator |
| Caps | 2 embedding recs, all staged promotion recs |
| Rollback | Disable timer |
| Kill switch | DISABLED file |
| Dashboard | Review section |

### Phase 40 — Governance Review

| Field | Value |
|-------|-------|
| Purpose | Full governance review before any broader autonomy |
| Requirements | All Phases 34–39 PASS, 30-day observation, operator audit |
| Decision scope | Whether to proceed to autonomous advisory or remain capped |
| Trading/proposal automation | NOT IN SCOPE — requires separate future governance |
