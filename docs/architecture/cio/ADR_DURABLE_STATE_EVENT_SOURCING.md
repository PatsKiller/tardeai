# ADR: Durable State Event Sourcing

**Status:** FROZEN (P-1.0 Architecture Freeze)
**Date:** 2026-08-08
**ADR ID:** CIO-P-1.0-EVENT-004
**Phase:** P-1.0 — Phase -1 Architecture Freeze
**Canonical Reference:** `CIO_PHASE_MINUS_1_PLAN_CORRECTED.md` v3.3, Corrections 5, 6

## Decision

Freeze event-sourced contracts for all durable CIO state. All persistent state is represented as append-only event streams. No mutation of prior records. Event log is authoritative; projections are derived and rebuildable.

## Event Streams

### 1. CIO Action Ledger

**Path:** `data/cio/cio_action_ledger.jsonl`
**Purpose:** Durable record of every CIO action taken by Alex

Event types:
- `CIO_ADVISORY_PRODUCED` — Alex generates a financial advisory
- `CIO_HEALTH_BLOCK_ACTIVATED` — Data quality block prevents advisory
- `CIO_HEALTH_BLOCK_CLEARED` — Block cleared, advisory resumes
- `CIO_CHALLENGE_ISSUED` — Alex issues a challenge to Hermes
- `CIO_CHALLENGE_RESOLVED` — Hermes challenge results incorporated
- `CIO_SPECIALIST_CONSULTED` — Alex consulted Guardian/Ledger/Steph
- `CIO_OPERATOR_RESPONDED` — Operator responded to CIO advisory
- `CIO_ACTION_FOLLOWUP_SCHEDULED` — Scheduled follow-up on prior action

### 2. Agent Handoff Queue

**Path:** `data/cio/agent_handoff_queue.jsonl`
**Purpose:** Durable handoff between Alex and specialists

Event types:
- `HANDOFF_ENQUEUED` — Initial creation
- `HANDOFF_CLAIMED` — Agent claims the handoff
- `HANDOFF_STARTED` — Processing begins
- `HANDOFF_RETRY_SCHEDULED` — Retry after failure
- `HANDOFF_COMPLETED` — Successful completion
- `HANDOFF_FAILED` — Terminal failure
- `HANDOFF_EXPIRED` — Deadline exceeded
- `HANDOFF_CANCELLED` — Operator/source cancellation

Handoff stream fields:
| Field | Type | Purpose |
|---|---|---|
| `handoff_id` | UUIDv7 | Stream ID (immutable) |
| `from_agent` | string | alex, maria, steph, guardian, ledger |
| `to_agent` | string | Target agent |
| `task_type` | enum | cio_question, risk_review, tax_check, challenge, research_request, wake, operator_request |
| `priority` | P1/P2/P3 | Processing priority |
| `deadline` | ISO8601 | Must-complete-by timestamp |
| `budget` | float | Max USD allowed for LLM calls on this handoff task |

### 3. Operator Notification Outbox

**Path:** `data/cio/notification_outbox.jsonl`
**Purpose:** OUTBOUND CIO → operator delivery. Separate from handoff queue and operator ingress.

Event types:
- `NOTIFICATION_ENQUEUED` — Notification created
- `DELIVERY_ATTEMPTED` — Delivery was attempted (record outcome)
- `DELIVERY_CONFIRMED` — Delivery verified
- `DELIVERY_RETRY_SCHEDULED` — Retry queued
- `NOTIFICATION_EXPIRED` — Past expires_at
- `NOTIFICATION_DEAD_LETTERED` — Terminal after max retries

Notification stream fields:
| Field | Type | Purpose |
|---|---|---|
| `notification_id` | UUIDv7 | Stream ID (immutable) |
| `cio_action_id` | UUID | Links to CIO action ledger event |
| `message_class` | enum | advisory, alert, escalation, status, checkin, confirmation |
| `severity` | enum | P0, P1, P2, INFO |
| `expires_at` | ISO8601 | After this, notification is stale |
| `dedupe_key` | string | Deterministic key to prevent duplicate delivery |

### 4. Hermes Challenge Jobs

**Path:** `data/cio/hermes_challenge_queue.jsonl`
**Purpose:** Durable challenge jobs for Hermes

Event types:
- `CHALLENGE_CREATED` — Alex creates a challenge
- `CHALLENGE_PICKED_UP` — Hermes picks up the challenge
- `CHALLENGE_IN_PROGRESS` — Hermes begins processing
- `CHALLENGE_RESOLVED` — Hermes returns findings
- `CHALLENGE_TIMED_OUT` — Hermes did not respond in time

Challenge types: `research_gap`, `contradiction`, `freshness_decay`, `source_quality`

## Universal Event Schema

Every event line in every JSONL stream carries these fields:

```
event_id | stream_id | event_type | occurred_at | prev_event_hash | payload_hash | event_hash | payload
```

| Field | Type | Description |
|---|---|---|
| `event_id` | UUIDv7 | Unique, time-ordered, monotonic |
| `stream_id` | UUIDv7 | Groups related events (e.g., a handoff and its lifecycle) |
| `event_type` | string | Domain-specific enum value |
| `occurred_at` | ISO8601 | Wall-clock time of the event |
| `prev_event_hash` | hex | SHA-256 of the previous event line (chains events within a stream) |
| `payload_hash` | hex | SHA-256 of the `payload` field |
| `event_hash` | hex | SHA-256 of the entire event line (excluding this field) |
| `payload` | JSON | Domain-specific event body |

### Hash Chain Integrity

```
event_1: prev_event_hash = "0000000000000000000000000000000000000000000000000000000000000000" (genesis)
event_2: prev_event_hash = SHA-256(event_1_line)
event_3: prev_event_hash = SHA-256(event_2_line)
...
event_n: prev_event_hash = SHA-256(event_{n-1}_line)
```

Chain is verified on every write and can be verified on any read.

## Atomicity Requirements

### Write Behavior

1. Acquire exclusive file lock (fcntl.flock)
2. Verify chain head (last `event_hash` matches expected, or genesis hash for first event)
3. Append single event line using O_APPEND (atomic at POSIX line boundary)
4. fsync the file descriptor
5. Release lock
6. Update derived manifest/projection afterward (lazy, async)
7. If derived update fails → recover/rebuild from event log

### The event log is authoritative. Manifest/index/projection is derived and rebuildable.

### Required Crash Test Scenarios

| Scenario | Test |
|---|---|
| Write-kill-recover | Write → SIGKILL mid-write → recover → verify no partial event, chain intact |
| Bulk restart | Write 50 events → kill process → restart → verify all events readable, chain verified, projection rebuilds correctly |
| Disk-full | Simulate ENOSPC → write fails → verify no corrupted event, lock released, previous chain intact |
| Concurrent collision | Two writers → second blocked by lock → retries or fails gracefully |

## Prohibited Patterns

| Prohibited | Correct Alternative |
|---|---|
| Mutating prior JSONL rows | Append new event (e.g., status change → new event_type) |
| Raw LLM filesystem writes | All writes by deterministic Python service |
| In-place status field updates | Represent state transitions as events; derive current status by replay |
| JSONL writes without lock/fsync | Always lock → append → fsync |
| Same stream ID + event_type written twice | Idempotency key: (stream_id, event_type) deduplication |
| Partial event writes | O_APPEND + fsync guarantees atomic line writes |

## Read Projections

Current state is derived by replaying the event stream:
```
FOR each event in stream (ordered by event_id):
  CASE event_type:
    HANDOFF_ENQUEUED → projection.handoffs[stream_id] = {status: "ENQUEUED", ...}
    HANDOFF_CLAIMED → projection.handoffs[stream_id].status = "CLAIMED"
    HANDOFF_COMPLETED → projection.handoffs[stream_id].status = "COMPLETED"
    ...
```

Projection is in-memory or SQLite read cache, rebuilt on restart from the authoritative event log.

## No Raw LLM Filesystem Writes

Alex must NEVER append directly to JSONL files. All writes go through deterministic Python service code:
- `cio_action_service.py` for action ledger writes
- `agent_handoff_service.py` for handoff queue writes
- `notification_outbox_service.py` for notification writes
- `hermes_challenge_service.py` for challenge writes

## Existing Infrastructure Reuse

- `scripts/lib/file_integrity.py` — `FileIntegrity.compute_sha256()` for event hashing
- `data/runtime/file_integrity_manifest.json` — extend to include CIO event stream file keys with chain head hashes

---

*Frozen by P-1.0 Architecture Freeze on 2026-08-08. Modification requires ADR amendment.*
