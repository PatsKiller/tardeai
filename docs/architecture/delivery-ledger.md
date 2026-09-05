# ChannelDelivery@v1 — Delivery Ledger

**Status:** Phase 3 implemented (ledger + typed client). **Does not own delivery.**  
**Schema version:** `ChannelDelivery@v1`  
**Code:** `scripts/lib/comms/delivery.py`  
**Migration:** `migrations/2026_09_05_communication_delivery_ledger.sql`  
**Gateway mode:** remains `OFF` by default; Phase 3 is SHADOW recording only.

---

## Purpose

Every delivery **attempt** for a `CommunicationEvent` gets a universal `ChannelDelivery@v1` row, independent of provider. Telegram is the first channel; Slack/Email/WhatsApp reuse the same shape later.

Provider message IDs (Telegram `message_id`, Slack `ts`, SMTP Message-ID, WhatsApp SIDs) live in `provider_message_id` / `provider_coordinates`. They are never the global primary key — `delivery_id` is.

Phase 3 records attempts in **SHADOW**: stubs are reserved after `publish_communication`, but the gateway does **not** claim egress ownership (`PublishResult.delivery_owned` stays `False`). Legacy transports (including `telegram_transport`) are **not** required to pass `event_id` yet.

---

## Row shape

| Field | Role |
|---|---|
| `delivery_id` | Global attempt PK (`dlv_` + uuid) |
| `attempt_id` | Attempt ordinal within `(event_id, channel)` (default `1`) |
| `event_id` | FK → `communication_events` (fail closed if missing) |
| `channel` | `telegram` first; others later |
| `adapter_version` | e.g. `telegram@v1` |
| `destination_policy_id` / `recipient_set_hash` / `render_variant_id` | Policy / audience / render lineage |
| `chunk_count` / `part_sequence` | Multi-part sends (Telegram splits) |
| `reply_thread_coordinates` | Reply/thread placement JSON |
| `idempotency_key` | Deterministic `didem_*` over event+channel+attempt |
| `status` | See lifecycle below |
| `request_fingerprint` / `response_fingerprint` | Rendered request / provider response hashes |
| `provider_message_id` / `provider_coordinates` | Provider receipt |
| `error_taxonomy` | Stable failure class (e.g. `provider.timeout`) |
| `reserved_at` / `sent_at` / `completed_at` | Attempt timeline |
| `retry_policy` | JSON retry hints |

Indexes: `event_id`, `status`, `channel`, `provider_message_id` (partial).

---

## Lifecycle

```
RESERVED → SENDING → SENT → DELIVERED → ACKNOWLEDGED
                ↘ FAILED / CANCELLED
RESERVED → SENT | FAILED | SUPPRESSED | EXPIRED | CANCELLED
FAILED → RESERVED | SENDING   (retry reopen)
```

Illegal transitions raise `DeliveryGateError`.

---

## Client API

| Function | Behaviour |
|---|---|
| `reserve_delivery(event_id=..., channel=...)` | Mint RESERVED row; fail closed without `event_id`; idempotent on `(event_id, channel, attempt_id)` |
| `attach_delivery_reservation(event_id, channel)` | Thin helper used after publish |
| `settle_delivery(delivery_id, status=..., provider_message_id=...)` | Status + receipt settlement; **no provider I/O** |
| `record_chunk(delivery_id, part_sequence=...)` | Multi-part chunk bookkeeping |

When DB/migration unavailable, the module falls back to an in-process memory store (same pattern as `publish_communication`).

`publish_communication` auto-calls `attach_delivery_reservation` for each outbound channel after a successful persist. Outbox `recorded` rows remain Phase 1 intent; delivery stubs are the attempt ledger.

---

## Mode semantics (Phase 3)

| Mode | Event ledger | Delivery stubs | Delivery ownership |
|---|---|---|---|
| OFF | Yes | Yes (RESERVED) | **No** — legacy still sends |
| SHADOW | Yes | Yes | **No** |
| CANARY / ACTIVE | Yes | Yes | **Not yet** — do not flip `COMMS_GATEWAY_MODE` for ownership |

---

## Non-goals (this phase)

- Requiring `event_id` inside `telegram_transport` (would break legacy)
- Flipping `COMMS_GATEWAY_MODE` to `ACTIVE`
- Provider network calls from `scripts/lib/comms/`
- Subject memory (Phase 4), producer migration (Phase 5+), other-channel ACTIVE cutover

---

## Tests

`tests/test_comms_delivery_ledger.py` — reserve→settle SENT, fail closed without `event_id`, idempotent reservation, memory fallback, status transitions, chunk recording, publish auto-reserve.
