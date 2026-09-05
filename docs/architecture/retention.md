# Librarian Retention — RetentionDecision@v1 (Phase 6)

**Status:** Phase 6 implemented (schema + library + tests).  
**Code:** `scripts/lib/comms/librarian.py`  
**Migration:** `migrations/2026_09_05_communication_librarian.sql`  
**Tests:** `tests/test_comms_librarian.py`  
**Contract:** `RetentionDecision@v1`

**Boundary:** The communications Librarian owns **lifecycle classification** for messages — not source truth. Chat must never auto-become institutional knowledge.

---

## Purpose

1. Classify each `CommunicationEvent` into a retention action + TTLs.
2. Persist decisions (and later execute expiry) without calling providers.
3. Tombstone purged content so lineage survives body deletion.
4. Allow **knowledge candidates** only with owner + provenance + explicit review.

Retention evaluation is async-capable; publish path does **not** require a synchronous librarian hook.

---

## Actions

| Action | Meaning |
|---|---|
| `KEEP` | Retain content; expiry pass does not purge |
| `COMPACT` | After TTL, compact narrative / drop bulky fields |
| `REDACT` | After TTL, redact sensitive body fields |
| `DELETE_CONTENT_KEEP_TOMBSTONE` | Purge body; keep tombstone + metadata lineage |
| `DELETE_ALL_ALLOWED` | Full delete permitted (rare; still tombstone recommended) |
| `HOLD` | Legal hold — deletes blocked |

---

## Retention-class heuristics

| `retention_class` | Content TTL | Default action |
|---|---|---|
| `operational_30d` | 30d | `DELETE_CONTENT_KEEP_TOMBSTONE` |
| `ops_7d` | 7d | `DELETE_CONTENT_KEEP_TOMBSTONE` |
| `inbound_7d` | 7d | `DELETE_CONTENT_KEEP_TOMBSTONE` |
| `approval_ttl` | 365d | `KEEP` (audit) |
| `research_365d` | 365d | `COMPACT` |
| `protection_365d` | 365d | `KEEP` |
| `audit_indefinite` | none | `KEEP` |

Unknown classes default to operational_30d behavior. Names ending in `_Nd` / `_Nh` parse a TTL when no explicit map entry exists.

`legal_hold=True` on the event forces `action=HOLD`, clears expiry, and blocks purge.

---

## Schema

| Table | Role |
|---|---|
| `communication_retention_decisions` | Decision rows (`decision_id` PK, `event_id`, TTLs, `action`, `receipt`) |
| `communication_tombstones` | Post-purge markers (`event_id` PK) |
| `communication_knowledge_candidates` | Promotion queue (`CANDIDATE` → review) |

Indexes: decisions by `event_id` / `expires_at`; candidates by `event_id` / `status`.

`event_id` is FK-ish TEXT (no hard FK to `communication_events`) so retention can track events that lived only in memory or were already tombstoned.

---

## API

| Function | Behavior |
|---|---|
| `classify_retention(event_like)` | Heuristic `RetentionDecision` from event dict or `CommunicationEvent` |
| `apply_retention_decision(...)` | Persist decision (DB when available, else memory) |
| `execute_expiry_pass(*, now=None, dry_run=True)` | Scan expired non-hold rows; **dry_run defaults True** |
| `propose_knowledge_candidate(event_id, assertion_text, *, owner, evidence_refs=…)` | Creates `CANDIDATE` only; refuses without owner/provenance |
| `decide_knowledge_candidate(candidate_id, status, *, reviewer)` | Explicit `ACCEPTED` / `REJECTED` / … |
| `reset_librarian_memory()` | Test helper |

### Expiry pass safety

- Default `dry_run=True` — reports `would_execute` without writing tombstones.
- `legal_hold` / `HOLD` never purge.
- `KEEP` is not executable by the expiry pass.

### Knowledge promotion safety

- `propose_knowledge_candidate` **never** sets `ACCEPTED`.
- Missing `owner` or empty `evidence_refs` → refuse.
- Acceptance requires `decide_knowledge_candidate(..., ACCEPTED, reviewer=…)`.

---

## Persistence fallback

When librarian tables (or DB) are unavailable, an in-process memory store mirrors Phase 1–5 behavior. Memory is not durable across processes; sufficient for OFF/SHADOW tests and dry runs.

---

## Non-goals

- Provider transport / sending
- Auto-promotion of chat to knowledge truth
- Synchronous publish-path retention (optional async later)
- Hermes research librarian (different scope — do not conflate)
- `/v3/communications` UI (Phase 7)
- Agent consumption receipts (Phase 8)

---

## Down migration

`migrations/2026_09_05_communication_librarian.down.sql` drops candidates, tombstones, then decisions.
