# Phase 2 Data Authority — Trade AI CIO

**Date:** 2026-08-08
**Phase:** P2.0 Authority Freeze
**Status:** FROZEN

---

## 1. Authoritative Data Domain Ownership

### Portfolio / Holdings

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | Data Broker (portfolio JSON, holdings database) |
| **access_control** | Read-only API for agents |
| **alex_read_permission** | YES (read-only, through Data Broker) |
| **alex_write_permission** | NO |
| **canonical_source** | Trade AI Data Broker |
| **version_policy** | Snapshot-based, timestamped |

### Performance / Attribution

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | Performance calculation services |
| **access_control** | Read-only API for agents |
| **alex_read_permission** | YES (read-only) |
| **alex_write_permission** | NO |
| **canonical_source** | Trade AI deterministic performance engine |
| **version_policy** | Calculation date, parameter version |

### Risk Evidence

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | Risk calculation services |
| **access_control** | Read-only API for agents |
| **alex_read_permission** | YES (read-only, through Guardian) |
| **alex_write_permission** | NO |
| **canonical_source** | Trade AI deterministic risk engine |
| **version_policy** | Calculation date, model version |

### Tax Lots / Cost Basis

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | Tax lot tracking, realized gains/losses |
| **access_control** | Read-only API for agents |
| **alex_read_permission** | YES (read-only, through Ledger) |
| **alex_write_permission** | NO |
| **canonical_source** | Trade AI tax lot engine |
| **version_policy** | Trade date, lot ID |

### IPS / Goals

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/operator_profile.jsonl` (P2.1) |
| **access_control** | Event-sourced, read + governed write |
| **alex_read_permission** | YES (OPERATOR_CONFIRMED facts only for advisory) |
| **alex_write_permission** | GOVERNED_WRITE (profile updates via cio_operator_profile.py) |
| **canonical_source** | `cio_operator_profile.py` event store |
| **version_policy** | Event-sourced, versioned, operator-confirmed |

### Operator Profile

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/operator_profile.jsonl` (P2.1) |
| **access_control** | Event-sourced, read + governed write |
| **alex_read_permission** | YES (OPERATOR_CONFIRMED facts only) |
| **alex_write_permission** | GOVERNED_WRITE (profile updates via cio_operator_profile.py) |
| **canonical_source** | `cio_operator_profile.py` event store |
| **version_policy** | Event-sourced, versioned, operator-confirmed |

### CIO Actions

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/cio_action_ledger.jsonl` |
| **access_control** | Append-only event store |
| **alex_read_permission** | YES (read actions) |
| **alex_write_permission** | GOVERNED_WRITE (create/update via CIOActionLedger) |
| **canonical_source** | `cio_action_ledger.py` event store |
| **version_policy** | Event-sourced, hash-chained, immutable |

### Agent Handoffs

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/agent_handoff_queue.jsonl` |
| **access_control** | Append-only event store |
| **alex_read_permission** | YES (read handoffs) |
| **alex_write_permission** | GOVERNED_WRITE (enqueue via AgentHandoffQueue) |
| **canonical_source** | `cio_agent_handoff_queue.py` event store |
| **version_policy** | Event-sourced, hash-chained, immutable |

### Health Decisions

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | CIOHealthBoundary internal state |
| **access_control** | Deterministic service, read-only for agents |
| **alex_read_permission** | YES (read health status) |
| **alex_write_permission** | NO |
| **canonical_source** | CIOHealthBoundary deterministic checks |
| **version_policy** | Scan timestamp |

### Wake Jobs

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/wake_jobs.jsonl` |
| **access_control** | Deterministic service |
| **alex_read_permission** | YES (read pending wakes) |
| **alex_write_permission** | NO (wakes are system-managed) |
| **canonical_source** | CIOWakeJobStore event store |
| **version_policy** | Event-sourced |

### Notifications

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/notification_outbox.jsonl` |
| **access_control** | Append-only event store |
| **alex_read_permission** | YES (read notification state) |
| **alex_write_permission** | GOVERNED_WRITE (enqueue via NotificationOutbox) |
| **canonical_source** | `cio_notification_outbox.py` event store |
| **version_policy** | Event-sourced, idempotent delivery |

### Hermes Challenges

| Field | Value |
|---|---|
| **owner** | Trade AI (Hermes) |
| **storage** | `data/cio/hermes_challenge_queue.jsonl` |
| **access_control** | Independent queue |
| **alex_read_permission** | YES (read challenges/results) |
| **alex_write_permission** | GOVERNED_WRITE (request challenge only — cannot edit results) |
| **canonical_source** | HermesChallengeQueue event store |
| **version_policy** | Event-sourced, Hermes-independent |

### CIO Runs

| Field | Value |
|---|---|
| **owner** | Trade AI |
| **storage** | `data/cio/cio_runs.jsonl` (P2.3) |
| **access_control** | Append-only event store |
| **alex_read_permission** | YES (read run state) |
| **alex_write_permission** | GOVERNED_WRITE (create/update via CIORunStore) |
| **canonical_source** | `cio_run.py` event store |
| **version_policy** | Event-sourced, hash-chained |

### Conversations / Preferences

| Field | Value |
|---|---|
| **owner** | OpenClaw |
| **storage** | OpenClaw conversation state, MEMORY.md, preferences |
| **access_control** | OpenClaw-managed |
| **alex_read_permission** | YES (non-authoritative, conversational context only) |
| **alex_write_permission** | YES (conversation/preferences within OpenClaw) |
| **canonical_source** | NON-AUTHORITATIVE for financial facts |
| **version_policy** | N/A (non-authoritative) |

---

## 2. Authority Rules

### Canonical Source Rule
For any financial fact, the canonical source is always Trade AI. OpenClaw conversation state, agent memory, and cached context are NON-AUTHORITATIVE.

### Fresh-Session Rule
Alex MUST reconstruct financial context from Trade AI authoritative state on every material CIO run. Never from OpenClaw MEMORY.md.

### Deterministic-First Rule
Numeric computations (risk, tax, performance, allocation) come from deterministic Trade AI services. LLMs explain, compare, challenge, summarize — they NEVER become the numeric source of truth.

### Write-Through Rule
All writes flow through deterministic service interfaces (event-sourced, hash-chained, fsync'd). No direct file append. No direct database write.

### Operator-Confirmed Rule
Only OPERATOR_CONFIRMED profile facts can support material financial advice. UNVERIFIED, SUPERSEDED, EXPIRED, or CONFLICTED facts must be flagged and not used for advisory.
