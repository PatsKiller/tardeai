# Phase 2 Trigger Ownership — Trade AI CIO

**Date:** 2026-08-08
**Phase:** P2.0 Authority Freeze
**Status:** FROZEN
**Rule:** One Trigger, One Owner. No duplicate financial schedules.

---

## 1. Trigger Ownership Registry

### Daily CIO Briefing

| Field | Value |
|---|---|
| **trigger** | Trade AI scheduled wake (cron: tradeai_cio_daily_briefing) |
| **owner** | Trade AI CIOWakeJobStore |
| **durable_state** | `data/cio/wake_jobs.jsonl` — SCHEDULED event |
| **consumer** | Alex (via future CIO dispatcher) |
| **retry_owner** | CIOWakeJobStore (exponential backoff, max 3 retries) |
| **delivery_owner** | CIO dispatcher → Alex → NotificationOutbox → Telegram |
| **frequency** | Daily (market days) |
| **cost_model** | Wake detector deterministic ($0); LLM cost only if Alex processes |
| **duplicate_check** | idempotency_key = `schedule:daily_briefing:{date}` |

### Weekly CIO Review

| Field | Value |
|---|---|
| **trigger** | Trade AI scheduled wake (cron: tradeai_cio_weekly_review) |
| **owner** | Trade AI CIOWakeJobStore |
| **durable_state** | `data/cio/wake_jobs.jsonl` — SCHEDULED event |
| **consumer** | Alex (via future CIO dispatcher) |
| **retry_owner** | CIOWakeJobStore (exponential backoff, max 3 retries) |
| **delivery_owner** | CIO dispatcher → Alex → NotificationOutbox → Telegram |
| **frequency** | Weekly (Saturday or Sunday) |
| **cost_model** | Wake detector deterministic ($0); LLM cost only if Alex processes |
| **duplicate_check** | idempotency_key = `schedule:weekly_review:{iso_week}` |

### Action Follow-Up Due

| Field | Value |
|---|---|
| **trigger** | CIOEventDetector (P-1.6) — action.next_check_at <= now |
| **owner** | Trade AI CIOEventDetector |
| **durable_state** | `data/cio/cio_action_ledger.jsonl` → follow-up due event |
| **consumer** | Alex (via CIO dispatcher) |
| **retry_owner** | CIOEventDetector (re-scans on next detection cycle) |
| **delivery_owner** | Alex → NotificationOutbox → Telegram |
| **frequency** | Event-driven (deterministic detector scan) |
| **cost_model** | Detector deterministic ($0); LLM cost only if Alex processes |
| **duplicate_check** | idempotency_key = `event:action_followup:{action_id}:{check_at}` |

### Health Block Started / Cleared

| Field | Value |
|---|---|
| **trigger** | CIOHealthBoundary (P-1.5) — health_decision event |
| **owner** | Trade AI CIOHealthBoundary |
| **durable_state** | CIOHealthBoundary internal state + CIOActionLedger (block action created) |
| **consumer** | Alex (notified via wake → dispatcher or blocking on run start) |
| **retry_owner** | CIOHealthBoundary (re-evaluates on next health scan) |
| **delivery_owner** | Alex → NotificationOutbox → Telegram (if unblock warrants notification) |
| **frequency** | Event-driven (health scan cycle) |
| **cost_model** | Health scan deterministic ($0); LLM cost only if Alex notified |
| **duplicate_check** | idempotency_key = `event:health_block:{block_id}` |

### Specialist Completion

| Field | Value |
|---|---|
| **trigger** | AgentHandoffQueue (P-1.4) — handoff.status → COMPLETED |
| **owner** | Trade AI AgentHandoffQueue |
| **durable_state** | `data/cio/agent_handoff_queue.jsonl` — COMPLETED event |
| **consumer** | CIOEventDetector → CIOWakeJobStore → Alex |
| **retry_owner** | CIOEventDetector (re-scans pending handoffs) |
| **delivery_owner** | Alex → NotificationOutbox → Telegram (if warrants notification) |
| **frequency** | Event-driven |
| **cost_model** | Detector deterministic ($0); LLM cost only if Alex processes |
| **duplicate_check** | idempotency_key = `event:handoff_completed:{handoff_id}` |

### Hermes Challenge Resolved

| Field | Value |
|---|---|
| **trigger** | HermesChallengeQueue (P-1.9) — challenge.status → RESOLVED |
| **owner** | Trade AI (Hermes) HermesChallengeQueue |
| **durable_state** | `data/cio/hermes_challenge_queue.jsonl` — RESOLVED event |
| **consumer** | CIOEventDetector → CIOWakeJobStore → Alex |
| **retry_owner** | CIOEventDetector (re-scans pending challenges) |
| **delivery_owner** | Alex → NotificationOutbox → Telegram (if warrants notification) |
| **frequency** | Event-driven |
| **cost_model** | Detector deterministic ($0); LLM cost only if Alex processes |
| **duplicate_check** | idempotency_key = `event:hermes_resolved:{challenge_id}` |

### Operator Message Ingress

| Field | Value |
|---|---|
| **trigger** | Telegram webhook / message reception |
| **owner** | Maria (message classification) |
| **durable_state** | Maria classification → AgentHandoffQueue (if CIO-level) |
| **consumer** | Alex (via handoff → wake → dispatcher) |
| **retry_owner** | AgentHandoffQueue (durable queue, not lost on failure) |
| **delivery_owner** | Alex → NotificationOutbox → Telegram (response) |
| **frequency** | Event-driven |
| **cost_model** | Maria classification ($0 if FAST lane); LLM cost for Alex synthesis |
| **duplicate_check** | idempotency_key = `event:message:{message_id}` |

### Outbound Notification Delivery

| Field | Value |
|---|---|
| **trigger** | NotificationOutbox (P-1.7) — notification.status → PENDING |
| **owner** | Trade AI NotificationOutbox |
| **durable_state** | `data/cio/notification_outbox.jsonl` — PENDING event |
| **consumer** | Delivery Worker (deterministic, not Alex) |
| **retry_owner** | Delivery Worker (exponential backoff, max 5 retries) |
| **delivery_owner** | Delivery Worker → Telegram (not Alex) |
| **frequency** | Event-driven (outbox polling) |
| **cost_model** | Deterministic ($0) — no LLM in delivery path |
| **duplicate_check** | idempotency_key = `delivery:{notification_id}:{attempt}` |

---

## 2. Duplicate Prevention

Each trigger enforces idempotency via a unique key:
- Scheduled: `schedule:{workflow}:{temporal_key}`
- Event-driven: `event:{event_type}:{entity_id}:{condition_key}`

WakeJobStore checks idempotency before creating new wake jobs. CIOEventDetector uses state comparison to avoid re-triggering on already-processed events.

---

## 3. Cost Model

| Trigger Type | Detector Cost | Processing Cost |
|---|---|---|
| Scheduled wake | $0 (deterministic) | LLM cost only if Alex processes |
| Action follow-up | $0 (deterministic scan) | LLM cost only if Alex processes |
| Health block | $0 (deterministic scan) | LLM cost only if Alex notified |
| Specialist completion | $0 (deterministic scan) | LLM cost only if Alex processes |
| Hermes resolved | $0 (deterministic scan) | LLM cost only if Alex processes |
| Operator message | $0 (FAST classification) | LLM cost for Alex synthesis |
| Notification delivery | $0 (deterministic delivery) | $0 (no LLM in delivery path) |

---

## 4. No Duplicate Schedules

The following workflows SHALL NOT have duplicate schedules:

- No OpenClaw crontab entries for financial scheduling
- No agent heartbeat loops for wake/polling
- No duplicate cron entries across Trade AI and OpenClaw
- No LLM-based heartbeat or polling

All financial scheduling is owned by Trade AI. All wake detection is deterministic.
