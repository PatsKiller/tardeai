# CIO Agent Handoff Queue — LAB Service (P-1.4)

Status:      HISTORICAL
as_of:       2026-08-08T18:02:23-04:00
Measured at: efcc51365 / not measured

## Overview

The Agent Handoff Queue is a deterministic, append-only, hash-chained event store that durably records specialist work requests from Alex to downstream agents (Maria, Steph, Guardian, Ledger, and future specialists). It is a LAB service — no production provider calls, no Telegram delivery, no autonomous agent execution.

## Separation of Concerns

| Concern | Owned By | NOT in Handoff Queue |
|---|---|---|
| CIO action lifecycle | `cio_action_ledger.py` (P-1.3) | |
| Operator notifications | Notification Outbox | |
| Hermes research | Hermes Bridge | |
| Agent handoff lifecycle | **cio_agent_handoff_queue.py (P-1.4)** | |

The handoff queue does NOT import or write to the CIO action ledger.

## Event Schema

All events follow the same envelope structure as P-1.3:

```json
{
  "schema_version": "1.0.0",
  "event_id": "<20-digit-us-timestamp>-<12-hex>",
  "stream_id": "<handoff_id>",
  "event_type": "HANDOFF_*",
  "occurred_at": "2026-08-08T...",
  "actor_type": "agent|system",
  "actor_id": "<agent_id>",
  "authority": "advisory|system",
  "prev_event_hash": "<sha256>",
  "payload_hash": "<sha256>",
  "payload": { ... },
  "metadata": {},
  "event_hash": "<sha256>"
}
```

### Event Types (12)

| Event Type | Description | Target Status |
|---|---|---|
| `HANDOFF_QUEUE_GENESIS` | Queue initialization | — |
| `HANDOFF_ENQUEUED` | Handoff created; target agent AVAILABLE | PENDING |
| `HANDOFF_BLOCKED` | Handoff created; target agent NOT_READY | BLOCKED |
| `HANDOFF_CLAIMED` | Specialist claims the handoff; lease starts | CLAIMED |
| `HANDOFF_STARTED` | Specialist begins work | STARTED |
| `HANDOFF_HEARTBEAT` | Reserved for future lease renewal | (no transition) |
| `HANDOFF_RETRY_SCHEDULED` | Failure with remaining retry attempts | RETRY_SCHEDULED |
| `HANDOFF_COMPLETED` | Specialist delivers artifact | COMPLETED |
| `HANDOFF_FAILED` | All retry attempts exhausted | FAILED |
| `HANDOFF_EXPIRED` | Deadline passed | EXPIRED |
| `HANDOFF_CANCELLED` | Manually cancelled | CANCELLED |
| `HANDOFF_RELEASED` | Claim released; returns to pool | PENDING |

## State Machine

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    ▼                                          │
              ┌─────────┐    enqueue     ┌───────────┐        │
    init ───▶ │ PENDING  │──────────────▶│  CLAIMED   │───┐    │
              └────┬─────┘               └─────┬─────┘   │    │
                   │                           │         │    │
            block  │                    ┌──────┼──────┐  │    │
                   ▼                    │      │      │  │    │
              ┌─────────┐          start│  fail│release│  │    │
              │ BLOCKED  │              ▼      ▼      │  │    │
              └─────────┘        ┌─────────┐┌──────────┐    │
                                 │ STARTED  ││  FAILED   │──┐│
                                 └────┬─────┘└──────────┘  ││
                                      │                    ││
                                 ┌────┼────┐               ││
                            fail │    │complete   retry    ││
                                 ▼    ▼          ┌────────┘│
                          ┌──────────────┐        │         │
                          │RETRY_SCHEDULED│───────┘         │
                          └──────────────┘                  │
                                 │                          │
                            claim│                          │
                                 ▼                          │
                          ┌─────────┐                       │
                          │ CLAIMED  │ (re-claim loop)      │
                          └─────────┘                       │
                                                            │
              ┌─────────┐     ┌──────────┐    ┌──────────┐  │
              │COMPLETED│     │ EXPIRED   │    │CANCELLED │◀─┘
              └─────────┘     └──────────┘    └──────────┘
              (terminal)       (terminal)      (terminal)
```

### Transitions

| From | Allowed Targets |
|---|---|
| PENDING | BLOCKED, CLAIMED, CANCELLED, EXPIRED |
| BLOCKED | PENDING, CANCELLED, EXPIRED |
| CLAIMED | STARTED, PENDING (release), EXPIRED, CANCELLED, FAILED, RETRY_SCHEDULED, COMPLETED |
| STARTED | COMPLETED, FAILED, EXPIRED, CANCELLED, RETRY_SCHEDULED |
| RETRY_SCHEDULED | CLAIMED, EXPIRED, CANCELLED, FAILED |
| FAILED | RETRY_SCHEDULED, CANCELLED |
| COMPLETED | (none) |
| EXPIRED | (none) |
| CANCELLED | (none) |

Invalid transitions are fail-closed: a `ValueError` is raised.

## Lease Design

- **Lease duration**: 5 minutes (`LEASE_DURATION_MINUTES`)
- **Claim token**: 32-char hex UUID generated at claim time; must be presented for `complete`, `fail`, `start`, `release`
- **Lease check**: `_get_active_claim()` verifies the lease hasn't expired AND the worker holds the claim
- **Expired lease**: Handoff becomes eligible for re-claim by another worker (projection shows CLAIMED/STARTED but `_get_active_claim()` returns None)
- **Concurrent safety**: File-level `fcntl.flock(LOCK_EX)` protects event appends; hash chain is auto-corrected inside the lock

## Retry Policy

- **Backoff**: 1m, 5m, 15m, 60m (exponential with ceiling)
- **Max attempts**: 3 (`MAX_RETRY_ATTEMPTS`)
- **Attempt tracking**: `attempt_number` in projection, incremented per claim
- **Failure flow**:
  - Attempt 1-2 → `HANDOFF_RETRY_SCHEDULED` with `retry_after` timestamp
  - Attempt 3 → `HANDOFF_FAILED` (terminal-with-retry: can also be CANCELLED)
- **Retry recovery**: CLAIMED status is required; RETRY_SCHEDULED must be re-claimed

## Budget Contract

- **Field**: `max_budget_usd` (required, non-negative number)
- **Validation**: Enforced at enqueue time; negative values and non-numeric values rejected
- **Settlement**: NOT implemented (future: P-1.5+). Budget is tracked for visibility only.

## Artifact Requirements

For `complete()`:
- `artifact_id`: Required
- `artifact_hash`: Required (SHA-256 of artifact content)
- `artifact_type`: Optional (defaults to "unknown")
- `artifact_schema_version`: Optional
- `summary`: Optional
- `evidence_refs`: Optional list of evidence references
- `model_provenance_ref`: Optional reference to model run

## Idempotency

- **idempotency_key**: Optional per-handoff key checked against all prior events in the stream
- **Duplicate detection**: If key matches, the original event is returned (no new write)
- **Scope**: Per-handoff stream only

## Agent Maturity Handling

| Agent | Status | Role | Enqueue Behavior |
|---|---|---|---|
| alex | REGISTERED | cio | Can enqueue; sends handoffs |
| maria | AVAILABLE | research | Can be target; handoff goes PENDING |
| steph | NOT_READY | allocation | Can be target; handoff goes BLOCKED |
| guardian | NOT_READY | risk | Can be target; handoff goes BLOCKED |
| ledger | NOT_READY | tax | Can be target; handoff goes BLOCKED |

- **NOT_READY policy**: `BLOCKED` — handoff is recorded but cannot be claimed until the agent matures
- **Rejected states**: NONE — all valid agents are accepted; readiness determines BLOCKED vs PENDING

## Task Type Governance

### Allowed (9)
`cio_question`, `fundamental_research`, `allocation_review`, `risk_review`, `tax_account_review`, `retirement_review`, `evidence_review`, `specialist_reconciliation`, `wake`

### Forbidden (10)
`execute_trade`, `submit_order`, `modify_position`, `approve_risk`, `change_stop`, `run_shell`, `restart_service`, `deploy_code`, `modify_config`, `send_telegram`

Unknown task types raise `ValueError` on enqueue.

## Integrity Verification

`verify_integrity()` checks:
1. **JSON validity**: Every line parses as valid JSON
2. **Payload hash**: `compute_payload_hash(event.payload) == event.payload_hash`
3. **Event hash**: `compute_event_hash(event_without_hash) == event.event_hash`
4. **Chain links**: `event.prev_event_hash == previous_event.event_hash`

Returns: `{"valid": bool, "total_events": int, "valid_events": int, "corrupt_events": [...], "chain_breaks": [...]}`

## Recovery

- **Event log is authoritative**: All state is derived via replay from the event log
- **No separate projection store**: State is rebuilt on each `get_handoff()` call
- **Corruption recovery**: Corrupt events are flagged by `verify_integrity()`; recovery requires manual intervention
- **Rollback**: Preserve the event file, disable writes

## Storage

- **Canonical path**: `data/cio/agent_handoff_queue.jsonl`
- **Lock file**: `data/cio/agent_handoff_queue.jsonl.lock`
- **Format**: JSONL (one JSON object per line, newline-delimited)
- **Genesis event**: Guarnatees non-empty, chain-starting event

## Future Integration Points (NOT implemented)

| Feature | Status | Phase |
|---|---|---|
| OpenClaw autonomous handoff | NOT implemented | Future |
| Alex model handoff tool | NOT implemented | P-1.5+ |
| Maria/specialist handoff tool | NOT implemented | Future |
| Specialist polling | NOT implemented | Future |
| Operator ingress | NOT implemented | Future |
| Notification outbox integration | NOT implemented | Future |
| Hermes bridge integration | NOT implemented | Future |
| Budget settlement | NOT implemented | Future |
| Heartbeat renewal | Event type reserved, NOT implemented | Future |

## Test Coverage

58 tests covering:
- Schema validation (empty, missing fields, partial)
- Valid enqueue (full lifecycle)
- Unknown agent rejection
- Target NOT_READY → BLOCKED
- Task type governance (allowed/forbidden/unknown)
- Idempotency (duplicate enqueue with same key)
- Duplicate handoff_id rejection (without idempotency key)
- Legal claim
- Double claim rejection (sequential)
- Concurrent claim (last write wins)
- Claim token validation (wrong token rejected)
- Lease info in projection
- Start after claim
- Complete with artifact
- Complete without artifact / without artifact_hash (rejected)
- Fail and retry
- Retry attempt limit (3 → FAILED)
- Failed can be cancelled
- Deadline expiry (past deadline claims rejected)
- Expire
- Expired claim rejection
- Invalid transition fail-closed (COMPLETED → cancel rejected)
- Terminal CANCELLED → expire rejected
- Hash chain integrity
- Payload hash verification
- Concurrent enqueue (5 threads, all succeed)
- Projection rebuild (full lifecycle)
- Event corruption detection
- Budget validation (negative, non-numeric)
- Parent CIO action reference
- No hidden CIO action mutation
- Cancel
- Release (return to PENDING, re-claimable)
- Release with wrong token (rejected)
- Zero provider calls
- List handoffs (status filter, agent filter)
- Canonicalize determinism
- Payload hash determinism
- Fresh queue integrity
- Missing input reference rejection
- Input snapshot_id accepted
- Claim non-existent
- BLOCKED cannot be claimed
- BLOCKED can be cancelled
- All allowed task types accepted
- All forbidden task types rejected
- Automatic claim token generation
- enqueue_handoff public API
- enqueue_handoff unauthorized rejection
