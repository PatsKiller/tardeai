# CIO Operator Notification Outbox LAB

**Phase:** P-1.7  
**Status:** LAB (not production activated)  
**Authoritative Source:** `data/cio/operator_notification_outbox.jsonl` (event log)  
**Module:** `scripts/lib/cio_notification_outbox.py`  
**Event Schema:** `scripts/lib/cio_notification_outbox.py::build_event`

## Purpose

The Operator Notification Outbox provides a durable, append-only, hash-chained event store for operator-facing notifications. It separates outbound delivery from inbound operator messaging and ensures deterministic state management independent of transport (Telegram, command center) failures.

This is **infrastructure only**. ZERO live Telegram sends. ZERO provider calls. ZERO production activation.

## Architecture

### Outbound / Inbound Separation

```
┌─────────────────────────────────────────────────────────┐
│                   CIO Notification Outbox               │
│                                                         │
│  Outbound (P-1.7)          │  Inbound (NOT P-1.7)      │
│  ─────────────────         │  ─────────────────         │
│  - Operator notifications  │  - Telegram callbacks      │
│  - Advisory/alert delivery │  - Operator commands       │
│  - Status/checkin delivery │  - Proposal approvals      │
│  - System notices          │  - 2FA codes (forbidden)   │
│                            │  - Credential requests     │
└─────────────────────────────────────────────────────────┘
```

### Event Log Pattern

Every write is:
- **Append-only** — no mutation of prior records
- **Hash-chained** — each event links to its predecessor via SHA-256
- **fsync'd** — every write flushed to disk under `fcntl` exclusive lock
- **Rebuildable** — projections are derived by replaying the event log

The event log is authoritative; projections (`get_notification`, `list_notifications`) are rebuildable and never persisted independently.

## Event Schema

### Event Types

| Event Type | Target Status | Description |
|---|---|---|
| `NOTIFICATION_ENQUEUED` | PENDING | Initial creation |
| `DELIVERY_CLAIMED` | CLAIMED | Worker claims notification for delivery |
| `DELIVERY_ATTEMPTED` | DELIVERING | Delivery attempt recorded |
| `DELIVERY_CONFIRMED` | DELIVERED | Delivery succeeded (terminal) |
| `DELIVERY_RETRY_SCHEDULED` | RETRY_SCHEDULED | Transient failure, backoff scheduled |
| `DELIVERY_RELEASED` | PENDING | Claim released (lease expired or worker done) |
| `NOTIFICATION_EXPIRED` | EXPIRED | TTL exceeded (terminal) |
| `NOTIFICATION_CANCELLED` | CANCELLED | Operator cancelled (terminal) |
| `NOTIFICATION_DEAD_LETTERED` | DEAD_LETTERED | All retries exhausted (terminal) |
| `NOTIFICATION_OUTBOX_GENESIS` | — | Store initialization |

### Event Envelope

```json
{
  "schema_version": "1.0.0",
  "event_id": "<20-digit-ts>-<12-char-hex>",
  "stream_id": "<notification_id>",
  "event_type": "NOTIFICATION_ENQUEUED",
  "occurred_at": "2026-08-08T19:05:00.123456+00:00",
  "actor_type": "agent|operator|system",
  "actor_id": "<actor>",
  "authority": "advisory|operator|system|delivery",
  "prev_event_hash": "<sha256>",
  "payload_hash": "<sha256-of-payload>",
  "payload": { ... },
  "metadata": {},
  "event_hash": "<sha256-of-full-envelope-excluding-event_hash>"
}
```

## State Machine

```
                    ┌─────────┐
                    │ PENDING │◄────────────────────────┐
                    └────┬───┬┘                         │
                    claim │   │ expire/cancel            │ release
                    ┌─────▼┐  │                         │
              ┌─────┤CLAIMED├──┤                         │
              │     └──┬───┘  │                         │
              │  attempt  │    │                         │
              │   ┌───────▼┐  │                         │
              │   │DELIVERING│ │                         │
              │   └──┬───┬──┘  │                         │
              │      │   │     │                         │
         confirm   retry dead_letter                     │
              │      │   │     │                         │
    ┌─────────▼┐ ┌──▼───┐ ┌──▼──────────┐  ┌──────────┐ │
    │DELIVERED │ │RETRY │ │DEAD_LETTERED │  │ EXPIRED  │ │
    └──────────┘ │SCHED.│ └──────────────┘  └──────────┘ │
                 └──┬───┘                       ┌────────┘ │
                    │ release                   │CANCELLED│
                    └───────────────────────────┴─────────┘
                        (back to PENDING)
```

### Valid Transitions

| From | To |
|---|---|
| PENDING | CLAIMED, EXPIRED, CANCELLED, DEAD_LETTERED |
| CLAIMED | DELIVERING, DELIVERED, PENDING, EXPIRED, CANCELLED, DEAD_LETTERED |
| DELIVERING | DELIVERED, RETRY_SCHEDULED, DEAD_LETTERED, PENDING |
| RETRY_SCHEDULED | PENDING, EXPIRED, CANCELLED, DEAD_LETTERED |

Terminal states: DELIVERED, EXPIRED, CANCELLED, DEAD_LETTERED — no further transitions allowed.

## Claim Leases

- Each `DELIVERY_CLAIMED` sets a `lease_expires_at` = `now + LEASE_DURATION_SECONDS` (60s)
- Claims carry a `claim_token` — all subsequent operations (attempt, confirm, retry, release) must present the matching token
- Double-claim is prevented via `fcntl` lock — the check and write happen atomically under `LOCK_EX`
- If a worker crashes, its lease expires; another worker can claim after release

## Retry / Backoff

```
Attempt 1: 30s backoff
Attempt 2: 120s backoff
Attempt 3: 600s backoff → DEAD_LETTERED
```

After `MAX_RETRY_ATTEMPTS` (3), the notification is dead-lettered. Dead-lettered notifications are preserved in the event log and queryable via `list_dead_lettered()`.

## Deduplication

### Semantic Dedupe

Notifications from the same source (CIO action, wake job, handoff, health decision) with the same `message_class` produce an identical `dedupe_key`:

```
sha256("action:<cio_action_id>|wake:<wake_job_id>|...|class:<message_class>")[:32]
```

### Idempotency

Explicit `idempotency_key` on the notification dict prevents duplicate creation. The dedupe check runs **before** validation, so duplicate submissions return the original event without error.

## Message Classes

### Allowed

`advisory`, `alert`, `status`, `checkin`, `confirmation_request`, `data_quality_block`, `data_quality_recovered`, `followup_due`, `specialist_complete`, `system_notice`

### Forbidden (rejected at enqueue)

`execute_trade`, `order_submission`, `risk_override`, `2fa_code`, `credential_request`, `secret_delivery`

## Channels

- `telegram` — supported, **live adapter disabled** (FakeDeliveryAdapter only for tests)
- `command_center` — supported, **live adapter disabled**

## Delivery Adapter Contract

```python
class DeliveryAdapter:
    def deliver(notification, channel, claim_token) -> dict:
        # Returns:
        #   on success: {"success": True, "external_message_id": str, "transport_receipt_hash": str}
        #   on failure: {"success": False, "error": str, "error_class": str}
```

Error classes: `TIMEOUT`, `CONNECTION_ERROR`, `RATE_LIMITED`, `CHANNEL_UNAVAILABLE`

## At-Least-Once Semantics

The outbox guarantees **at-least-once** external delivery:
- A notification may be re-delivered after a crash (confirm not persisted before crash)
- The `external_message_id` and `transport_receipt_hash` provide idempotency at the transport layer
- **Exactly-once is not claimed** — it's the transport's responsibility to deduplicate

## Cross-Service References

Notifications can reference:
- `cio_action_id` — linking to a CIO Action Ledger entry (P-1.3)
- `wake_job_id` — linking to a wake job (P-1.6)
- `handoff_id` — linking to an agent handoff (P-1.4)
- `health_decision_id` — linking to a health boundary decision (P-1.5)

These references feed into semantic deduplication and are stored in the event payload.

## Integrity Verification

`verify_integrity()` checks:
1. **JSON validity** — every line must parse
2. **Payload hash** — `compute_payload_hash(payload)` must match `payload_hash`
3. **Event hash** — `compute_event_hash(event_without_hash)` must match `event_hash`
4. **Chain continuity** — `prev_event_hash` must match previous event's `event_hash`

## Telegram Resilience

- All Telegram sender modules (`telegram_alert_router.py`, `telegram_callback_policy.py`, etc.) are **unmodified** by P-1.7
- The outbox does not import or call any Telegram modules
- Live delivery is explicitly disabled — delivery workers are not activated
- The `FakeDeliveryAdapter` exists for testing only

## Rollback

To rollback P-1.7:
1. Stop any delivery workers (none running by default)
2. Preserve the event file `data/cio/operator_notification_outbox.jsonl`
3. Disable new writes by removing or renaming the module import
4. Existing notifications remain in the event log but no new events are written

## No Live Activation

- **Production delivery worker:** disabled
- **Production delivery schedule:** disabled
- **Live Telegram adapter:** disabled
- **Live command_center adapter:** disabled
- **Scheduler (cron/systemd):** unchanged
- **Heartbeat:** unchanged
- **Cost cap:** unchanged
- **Broker authority:** unchanged
- **Risk authority:** unchanged

## Test Coverage

79 tests covering:
- Schema validation and forbidden message classes
- Idempotency and semantic deduplication
- Claim/lease lifecycle (acquire, release, double-claim prevention, concurrency)
- Full delivery flow (enqueue → claim → attempt → confirm)
- Retry backoff and dead-letter after exhaustion
- Expiry and cancellation
- Hash chain and payload integrity verification
- Corruption detection and recovery
- Crash recovery scenarios
- Fake delivery adapter (success, timeout, retry)
- Structural safety (no provider calls, no live Telegram, no scheduler changes)
- Cross-module containment (no hidden mutation of CIO actions, wake jobs, handoffs)

All tests use `tempfile.TemporaryDirectory()` — the canonical `data/cio/operator_notification_outbox.jsonl` is never touched.
