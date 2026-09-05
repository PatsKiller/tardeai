# Agent Consumption Contracts — AgentConsumptionReceipt@v1

**Status:** Phase 8 implemented (subscriptions + receipts + influence lineage).  
**Schema version:** `AgentConsumptionReceipt@v1`  
**Code:** `scripts/lib/comms/agent_contracts.py`  
**Migration:** `migrations/2026_09_05_communication_agent_consumption.sql`  
**Tests:** `tests/test_comms_agent_contracts.py`

Persistent agents (CIO, Hermes, Advisory, Darwin, Maria, and future agents) **subscribe** to communication events via contracts, **acknowledge** consumption, emit **AgentConsumptionReceipt@v1**, and **declare influence lineage**. No consuming agent may self-certify institutional truth.

---

## Purpose

1. Explicit subscription filters so agents only see intended message classes / severities / subject domains.
2. Durable consumption receipts proving an agent retrieved or used a ledger event for a stated purpose.
3. Influence declarations linking derived work back to source `event_id`s.
4. Hard reject of self-certification: consumers never stamp `knowledge_status=ACCEPTED` (or other truthy institutional statuses) on events.

---

## Known agents

| `agent_id` | Role (informational) |
|---|---|
| `cio` | Chief investment / orchestration agent |
| `hermes` | Research / intelligence |
| `advisory` | Advisory drafting |
| `darwin` | Decision / evolution loops |
| `maria` | Operator-facing specialist |

Unknown agents are **rejected by default**. Pass `allow_unknown=True` to register / emit for future agents.

---

## Schema

| Table | Role |
|---|---|
| `communication_agent_subscriptions` | Per-agent filter subscription (`message_classes`, `severities`, `subject_domains`) |
| `communication_agent_consumption_receipts` | `AgentConsumptionReceipt@v1` rows |

### Subscriptions

| Column | Notes |
|---|---|
| `subscription_id` | PK (`sub_` + uuid) |
| `agent_id` / `agent_version` | Consumer identity |
| `filter` | JSONB: `message_classes[]`, `severities[]`, `subject_domains[]` |
| `enabled` | Disabled subs are ignored by eligibility |
| `created_at` | Mint time |

Empty filter lists mean **match-all** for that dimension.

### Receipts

| Column | Notes |
|---|---|
| `receipt_id` | PK (`acr_` + uuid) |
| `agent_id` / `agent_version` | Consumer |
| `event_id` / `thread_id` | Source communication identity |
| `artifact_ids` | Retrieved artifact refs |
| `purpose` | Why the agent consumed the event |
| `policy_decision` | Optional allow/deny annotation |
| `retrieved_at` / `acknowledged_at` | Timeline |
| `derived_artifact_ids` | Artifacts produced after consumption |
| `influence_declaration` / `influence_event_ids` | Lineage claim |

Unique index on `(agent_id, event_id, purpose)` (soft uniqueness / upsert guard).

---

## API

| Function | Behavior |
|---|---|
| `register_subscription(agent_id, *, agent_version, filter=None, allow_unknown=False)` | Create subscription row |
| `list_subscriptions(agent_id=None)` | List (optionally per agent) |
| `eligible_events_for_agent(agent_id, events)` | Apply enabled subscription filters |
| `emit_consumption_receipt(agent_id, *, event_id, purpose, …)` | Mint receipt; rejects self-certification kwargs |
| `acknowledge_consumption(receipt_id)` | Set `acknowledged_at` |
| `declare_influence(receipt_id, influence_declaration, influence_event_ids)` | Attach lineage |
| `assert_not_self_certifying_truth(agent_id, claimed_status)` | Raises on ACCEPTED / truthy statuses |
| `get_consumption_receipt(receipt_id)` | Lookup |
| `reset_agent_contracts_memory()` | Test helper |

### Self-certification ban

`assert_not_self_certifying_truth` and `emit_consumption_receipt` reject claimed statuses in:

`ACCEPTED`, `CERTIFIED`, `CANONICAL`, `AUTHORITATIVE`, `INSTITUTIONAL_TRUTH`, `TRUTH`, `VERIFIED_TRUTH`

(case-insensitive). There is **no** helper in this module that writes `knowledge_status=ACCEPTED` onto a `CommunicationEvent`. Institutional acceptance remains an operator / separate governance path.

---

## Persistence fallback

When agent tables (or DB) are unavailable, an in-process memory store mirrors Phase 1–5 ledger behavior. Memory is not durable across processes; sufficient for OFF/SHADOW tests and dry runs.

---

## Non-goals

- Provider transport / sending (Phase 3 owns delivery stubs; no provider calls here)
- UI surfaces (Phase 7)
- Librarian retention table edits (Phase 6)
- Promoting or accepting knowledge into institutional truth

---

## Down migration

`migrations/2026_09_05_communication_agent_consumption.down.sql` drops receipts then subscriptions.
