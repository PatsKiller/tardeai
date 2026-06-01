# Phase 36E — Scheduled Job Migration Plan

**Date:** 2026-06-01
**Status:** COMPLETE — plan only, no implementation

---

## Migration Phases

### Phase 41 — Migrate Safest 5 Jobs to Systemd Timers

| Candidate | Current | Risk |
|-----------|---------|------|
| Telegram command handler (2-min poll) | cron | LOW — should be a service |
| News ingestion (3 invocations) | cron | LOW — consolidate to 1 timer |
| System health agent (3 invocations) | cron | LOW |
| Maturity control board (2 invocations) | cron | LOW |
| Governance status (2 invocations) | cron | LOW |

Requirements: preflight, rollback, lock validation, log validation, operator approval.

### Phase 42 — Consolidate Duplicate Market Scan Jobs

| Target | Current | After |
|--------|---------|-------|
| finviz_screener (7) + screener_pm (6) | 13 crons | 1 pipeline controller |
| proactive_quote_refresh (11) | 11 crons | 1 smart refresher |

### Phase 43 — Pipeline Controller for Related Jobs

| Pipeline | Jobs Merged |
|----------|------------|
| Morning prep pipeline | ~8 pre-market jobs → 1 controller |
| Agent dispatch pipeline | router + intelligence + research (9) → 1 |

### Phase 44 — Event-Driven Queue Pilot

| Candidate | Trigger |
|-----------|---------|
| Catalyst ingestion on news arrival | PG NOTIFY on news_articles INSERT |
| Research backlog event | PG NOTIFY on hermes_research_intelligence INSERT |

### Phase 45 — Cron Retirement Wave 1

Remove 10–15 jobs confirmed redundant/superseded after Phases 41–44.

### Phase 46 — Command Center Scheduled Job Health Dashboard

Read-only dashboard showing:
- Active timers with last-run status
- Active cron job count
- Failed-job alerts
- Lock file health

---

## Each Phase Requires

- [ ] Preflight checks
- [ ] Rollback plan
- [ ] No missed-run guard
- [ ] Lock validation
- [ ] Log validation
- [ ] Health check
- [ ] Operator approval

**No migrations are executed in Phase 36.**
