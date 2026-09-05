# CommunicationEvent@v2 — Architecture

**Status:** Phase 1 implemented (ledger + typed client). **Does not own delivery.**  
**Schema version:** `CommunicationEvent@v2`  
**Code:** `scripts/lib/comms/`  
**Migration:** `migrations/2026_09_05_communication_event_ledger.sql`  
**Gateway mode env:** `COMMS_GATEWAY_MODE` = `OFF` (default) \| `SHADOW` \| `CANARY` \| `ACTIVE`

---

## Purpose

Every logical communication (inbound or outbound) receives a canonical ledger identity **before** business processing completes and **before** any provider call is allowed in later phases.

Telegram message IDs, Slack `thread_ts`, email Message-IDs, and WhatsApp SIDs are **provider coordinates**, never global primary keys.

---

## Identity rules

1. `event_id` — UUIDv7 (or uuid4 fallback), minted once at `publish_communication` / `mint_identity`.
2. `idempotency_key` — deterministic hash of producer + event_type + subject_key + intended_action + entity_refs + observation_version. Retries collide; new observations do not.
3. `subject_key` / `thread_id` / `correlation_id` / `causation_id` — lineage for subject memory (Phase 4).
4. `incident_id` — optional lifecycle identity for recurring conditions.
5. Entity GUIDs live in `entity_refs`; they identify subjects, not messages.

---

## Fail-closed gate

`publish_communication` rejects (no persist) when required fields are missing:

- Always: `direction`, `event_type`, `message_class`, `producer`, `subject_key`, `retention_class`
- Outbound: audience + delivery channels
- Classes `approval`, `protection_incident`, `broker_fact`, `order_state`, `risk_limit`, `account_fact`: non-empty `protected_facts` + `authoritative_sources`

No provider adapter may be invoked without a successful publish that yields `event_id` (enforced in Phase 2+).

---

## Persistence

| Table | Role |
|---|---|
| `communication_events` | Canonical ledger row |
| `communication_outbox` | Per-channel intent (`status=recorded` in Phase 1) |
| `communication_entity_links` | Entity index |

When DB/migration unavailable, Phase 1 falls back to an in-process memory store so OFF/SHADOW producers can still mint identity in tests and dry runs. Memory is not durable across processes.

---

## Mode semantics (Phase 1)

| Mode | Ledger write | Delivery ownership |
|---|---|---|
| OFF | Yes (memory or DB) | **No** — legacy paths still send |
| SHADOW | Yes | **No** |
| CANARY | Yes | Not yet implemented in client |
| ACTIVE | Yes | Not yet implemented in client |

`PublishResult.delivery_owned` is **always False** in Phase 1, even if `COMMS_GATEWAY_MODE=ACTIVE`.

---

## Producer adapters

- `scripts/lib/comms/adapters.from_alert_event` — maps `AlertEvent` → `CommunicationEvent`
- `scripts/lib/comms/adapters.from_plain_message` — maps free-text producer bodies

These are construction helpers only. Migrating producers to call `publish_communication` is Phase 5+.

---

## Non-goals (Phase 1 ledger)

- Provider transport / chokepoint zeroing (Phase 2 — static ratchets landed)
- Delivery receipts settlement (Phase 3)
- Subject memory retrieval (Phase 4)
- Librarian retention execution (Phase 6)
- ~~`/v3/communications` UI (Phase 7)~~ — see `docs/architecture/communications-workspace.md`
- Agent consumption receipts (Phase 8)

Controlled curation + `CurationReceipt@v1` is Phase 5 — see
`docs/architecture/curation-and-provenance.md`.

---

## Tests

`tests/test_comms_communication_event.py` — identity uniqueness, idempotency stability, fail-closed gates, memory persist, duplicate handling, delivery_owned=False invariant.
