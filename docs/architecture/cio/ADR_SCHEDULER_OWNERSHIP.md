# ADR: Scheduler Ownership

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-SCHED-006
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Corrections 3, 7

## Decision

Freeze scheduler ownership across five domains. No migration of financial cadence to OpenClaw cron. Financial wake detection is deterministic ($0 cost). OpenClaw owns conversational heartbeat only.

## Scheduler Ownership Matrix

| Function | Owner | Rationale |
|---|---|---|
| Deterministic financial / event detection | Trade AI | Cost-free, reliable, timezone-aware, existing infrastructure |
| Durable financial jobs (CIO wake, scheduled scans, periodic synthesis) | Trade AI | Jobs must survive OpenClaw restart, must have deduplication, must have restart recovery |
| Conversational heartbeat (session housekeeping) | OpenClaw | OpenClaw-native concern, no financial impact, no paid model calls |
| Hermes research loops | Hermes (Trade AI crontab trigger) | Hermes coordinator owns research schedule; independent of Alex |
| Ops remediation | Health / Escalation (Trade AI crontab) | Must remain outside Alex authority |
| Operator delivery | Durable outbox → OpenClaw / Telegram | Outbox writes are Trade AI; delivery is OpenClaw/Telegram |
| Operator ingress | Telegram/Maria → Agent Handoff Queue | Inbound path, separate from outbox |

## Deterministic CIO Wake Architecture

Per v3.3 Correction 3: Financial monitoring must NOT depend on periodic model calls.

```
Layer 1 — Deterministic Event Detector (Trade AI, $0 cost, no model):
  - Trade AI cron/service checks material conditions (health, data quality, market hours, events)
  - IF material change detected (health degradation, new operator message, scheduled CIO job)
  - THEN: create durable CIO wake job in Trade AI job queue
  - IF no material change → silence, no model call ever

Layer 2 — Durable CIO Wake (Trade AI → OpenClaw handoff):
  - Trade AI pushes wake job to Agent Handoff Queue
  - OpenClaw Alex receives durable wake/handoff on next poll
  - Alex evaluates job context (read-only: health score, action ledger, Hermes)

Layer 3 — Governed LLM Call (only if synthesis required):
  - IF job requires CIO synthesis (advisory, recommendation, challenge)
  - THEN: Alex issues governed LLM call through Trade AI LLM Gateway
  - IF job is status-only or informational → Alex acknowledges, no model call
```

## Deterministic Wake Trigger Sources

Per v3.3 Correction 7, the corrected trigger sources:

1. **Scheduled CIO job due** — deterministic timer (daily 5 AM, weekly Sun 8 AM, monthly 1st)
2. **Material portfolio/market event** — price threshold, stop trigger, regime change
3. **Health boundary state transition** — data_quality crossing threshold, system state change
4. **Inbound operator/CIO request** — Telegram/Maria → operator command/message ingress → classified request → Agent Handoff Queue → Alex (separate from notification outbox)
5. **Specialist handoff ready** — Guardian/Ledger/Steph critique complete
6. **Hermes challenge resolution** — Hermes returned findings
7. **Action-ledger follow-up condition due** — prior CIO action follow-up time reached

## Prohibited Scheduler Patterns

| Prohibited | Reason |
|---|---|
| OpenClaw cron for financial cadence | Financial jobs must survive OpenClaw restart; deduplication; restart recovery |
| Model calls during wake detection | Wake detection is deterministic, $0 cost |
| Duplicate schedules across Trade AI and OpenClaw | Single owner; OpenClaw must not duplicate Trade AI schedules |
| HEARTBEAT.md with model triggers | Financial monitoring must use deterministic $0 wake, not periodic LLM calls |
| Moving legacy Trade AI cron to OpenClaw | Financial jobs stay with Trade AI |
| Conflating inbound operator path with outbound | Separate ingress path vs notification outbox |

## Legacy Cron Inventory

Existing crontab entries that must NOT be duplicated in OpenClaw:

| Cron Entry | Current Schedule | Legacy Path | Replacement |
|---|---|---|---|
| `run_alex_daily.py` | Daily 5 AM | Trade AI crontab → script → direct model call | CIO daily wake job → Agent Handoff Queue → Alex governed LLM call |
| `run_alex_daily.py` | Weekly Sun 8 AM | Trade AI crontab → script → direct model call | CIO weekly wake job |
| `run_alex_daily.py` | Monthly 1st 9 AM | Trade AI crontab → script → direct model call | CIO monthly wake job |
| `alex_hygiene.py` | Mon-Fri 7:15 AM | Trade AI crontab → script | Evaluate: financial or conversational? Route accordingly |
| `alex_gov_research.py` | Mon 6 AM | Trade AI crontab → script | Hermes challenge job or CIO wake job |

## Legacy Cron Retirement Path

1. Document all legacy cron entries (P-1.6: `docs/operations/LEGACY_CRON_INVENTORY.md`)
2. For each entry, specify the target replacement mechanism
3. No new OpenClaw cron schedules for financial cadence
4. After P-1.6 "Deterministic CIO Wake/Event Detector" is operational, retire legacy cron entries one at a time with operator approval
5. Retirement trigger: replacement proves reliable for 7 consecutive days

## Conversational Heartbeat (OpenClaw, Separate)

OpenClaw may retain a conversational heartbeat mechanism for session housekeeping (e.g., "is this conversation still alive?"), but:
- Must be a no-model heartbeat (no paid LLM calls)
- Is unrelated to financial monitoring
- Must not consume paid model calls
- If OpenClaw has no native no-model heartbeat mechanism, do NOT emulate one with LLM calls

## Implementation Sequence

P-1.6 creates the deterministic CIO event detector. Legacy cron continues until retirement approved. The sequence is:

1. P-1.6: Build and deploy deterministic wake detector (alongside legacy cron)
2. P-1.6: Document legacy cron inventory
3. Observe wake detector for 7 consecutive days
4. Operator approves retirement of each legacy entry
5. Retire legacy entries one at a time

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires ADR amendment.*
