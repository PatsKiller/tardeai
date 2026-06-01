# Hermes Phase 33B — Scheduler Policy

**Date:** 2026-06-01
**Status:** AUTHORITATIVE — governance document

---

## Preferred Scheduler by Component Type

| Component Type | Scheduler | Reason |
|---------------|-----------|--------|
| Hermes recurring research loops | systemd user timer | Kill switch, journal logging, restart policy, dashboard status |
| Hermes gateway/sidecars | systemd user service | Always-on, auto-restart, lingering |
| Contained infrastructure (SearXNG) | Docker Compose | Isolated, portable, volume management |
| Trade AI pipeline jobs | cron (legacy) | 187 existing jobs, migration deferred |
| Simple one-shot tasks | cron or manual | Low complexity |

## Policy Rules

1. **All Hermes research loops MUST use systemd user timers** — not cron
2. **No hidden root cron for Hermes research** — all Hermes scheduling under johnclaw user
3. **No autonomous broker/proposal/journal mutations** from any scheduler
4. **All recurring research loops must have:**
   - max_rows cap
   - max_runtime timeout
   - log path
   - kill switch (DISABLED file)
   - dashboard status visibility
   - rollback/disable command
5. **Docker Compose for infrastructure only** — not for research scripts
6. **Cron migration is deferred** — 187 legacy jobs remain as-is until a dedicated migration phase

## Cron Migration Candidates (Future)

| Job Category | Priority | Reason |
|-------------|----------|--------|
| Drive doc sync | LOW | Simple, working, no urgency |
| Telegram command handler | MEDIUM | Should be a service, not 2-min cron |
| Data gap resolver | LOW | Hourly market-hours, working |
| Deep LLM window | LOW | Friday-only, working |

## Never Automate via Scheduler

- Broker execution decisions
- Proposal creation/approval
- Journal writes
- Holdings mutations
- Model routing changes
- .env modifications
- Production schema changes
