# Subject Memory / SubjectThread@v1 — Architecture

**Status:** Phase 4 implemented (schema + library + publish hook).  
**Code:** `scripts/lib/comms/subject_memory.py`  
**Migration:** `migrations/2026_09_05_communication_subject_memory.sql`  
**Tests:** `tests/test_comms_subject_memory.py`

**Naming boundary:** This is **not** `cio_rehydrate` / instrument cognition. Do not overload that module. Subject memory is the communications-gateway answer to “What happened previously on this exact subject?” across channels, consulted **before** curation.

---

## Purpose

1. Stable **subject** identity (`subject_key`) spanning Telegram / Email / Slack / WhatsApp memberships.
2. Thread membership linking ledger `event_id`s to a subject with optional provider coordinates.
3. **Policy-eligible** history retrieval only (default), so ineligible chatter does not enter curation context.

---

## Schema

| Table | Role |
|---|---|
| `communication_subjects` | Subject metadata: domain, entities, aliases, activity window, latest_state, open_questions, operator_decisions, outcomes |
| `communication_thread_membership` | `(subject_key, event_id)` membership + channel + provider_coordinates |

Domains (CHECK): `symbol` \| `account` \| `incident` \| `proposal` \| `research` \| `system` \| `operator`.

Indexes: `last_activity_at`, `(domain, last_activity_at)`, membership by `event_id` and `(subject_key, joined_at)`.

---

## `subject_key_for(domain, **parts)`

Deterministic key minting:

- Single primary part → `domain:value` (e.g. `symbol:AAPL`, `system:watchdog`).
- Multiple parts → `domain:k=v:…` with **sorted** keys (order-independent).

Symbols are uppercased. Invalid domains raise `ValueError`.

---

## API

| Function | Behavior |
|---|---|
| `upsert_subject(...)` | Create/update subject row (DB or memory) |
| `attach_event_to_subject(subject_key, event_id, channel=…, provider_coordinates=…)` | Idempotent membership; ensures subject exists |
| `retrieve_subject_history(subject_key, *, limit=50, eligible_only=True)` | History list with `artifact_kind` ∈ {`evidence`, `summary`} |
| `get_subject(subject_key)` | Metadata lookup |

### Eligibility

When `eligible_only=True` (default), events whose `knowledge_eligibility` is empty / `ineligible` / `none` / `denied` / `blocked` are omitted. Membership stubs without an event body cannot prove eligibility and are omitted under that flag.

### Artifact kind

- `summary` — `curation_mode` in `LLM_SUMMARY` / `TEMPLATE`, or short_summary without sanitized_body
- `evidence` — otherwise

---

## Publish hook

After a successful `publish_communication` persist, the client **lazy-imports** `attach_event_to_subject` and records membership for `event.subject_key` (first channel + provider_coordinates). Failures never fail the publish.

---

## Persistence fallback

When subject tables (or DB) are unavailable, an in-process memory store mirrors Phase 1 ledger behavior. Memory is not durable across processes; sufficient for OFF/SHADOW tests and dry runs.

---

## Non-goals

- Provider transport / sending
- LLM curation (Phase 5) — subject history is an **input** to curation, not curation itself
- Librarian retention execution
- Replacing CIO instrument records / `cio_rehydrate`

---

## Down migration

`migrations/2026_09_05_communication_subject_memory.down.sql` drops membership then subjects.
