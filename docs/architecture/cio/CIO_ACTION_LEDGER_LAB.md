# CIO Action Ledger LAB — P-1.3 Implementation

**Status:** FROZEN (P-1.3 LAB)
**Date:** 2026-08-08
**Canonical Reference:** `data/cio/cio_action_ledger.jsonl`
**Service Module:** `scripts/lib/cio_action_ledger.py`
**Test Suite:** `tests/test_cio_action_ledger.py` (29 tests, all PASS)

---

## 1. Why Legacy Tables Are Not the Ledger

The legacy PostgreSQL tables (`cio_decisions`, `cio_decision_responses`,
`alex_hygiene_log`) are pre-event-source pipeline records that:

- Allow **in-place mutation** of rows — the ledger is strictly append-only.
- Have **no hash chain** — the ledger cryptographically verifies every event.
- Are **co-located with Alex's model runtime** — the ledger is an isolated LAB
  service without provider/LLM access.
- Cannot be **replayed to rebuild projections** — the ledger is fully replayable.

These tables are **preserved and remain distinct**. P-1.3 does not migrate,
read, or modify them.

---

## 2. Event Schema

Every line in `cio_action_ledger.jsonl` carries:

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | string | Always `"1.0.0"` |
| `event_id` | string | `{microsecond_ts}-{uuid_hex}` for total ordering |
| `stream_id` | string | `cio_action_id` for action events, `ledger-genesis` for genesis |
| `event_type` | string | One of 13 canonical event types (see §3) |
| `occurred_at` | ISO8601 | UTC timestamp at event construction |
| `actor_type` | enum | `agent`, `operator`, `system` |
| `actor_id` | string | Agent identifier (e.g. `alex`, `operator`, `p1_3_init`) |
| `authority` | enum | `advisory` (agents), `operator` (operators), `system` |
| `prev_event_hash` | hex(64) | SHA-256 of the previous event in the global chain |
| `payload_hash` | hex(64) | SHA-256 of the canonicalized `payload` |
| `event_hash` | hex(64) | SHA-256 of the full envelope (sans `event_hash` itself) |
| `payload` | object | Domain-specific event data (see §4) |
| `metadata` | object | Extensible metadata (default `{}`) |

### Payload Fields (CIO_ACTION_CREATED)

| Field | Type | Required | Notes |
|---|---|---|---|
| `cio_action_id` | string | Yes | Immutable stream ID |
| `status` | string | Auto | Always `"OPEN"` on create |
| `priority` | string | No | `HIGH`, `MEDIUM`, `LOW` (default `MEDIUM`) |
| `domain` | string | No | e.g. `PORTFOLIO`, `TAX`, `RISK`, `GENERAL` |
| `title` | string | Yes | Human-readable action title |
| `recommendation` | string | No | Alex recommendation text |
| `why_now` | string | No | Trigger reasoning |
| `evidence_refs` | [string] | No | Reference IDs (snapshots, reports) |
| `affected_accounts` | [string] | No | Account identifiers |
| `affected_symbols` | [string] | No | Ticker symbols |
| `estimated_financial_impact` | string | No | Financial impact description |
| `estimated_tax_impact` | string | No | Tax impact description |
| `risk_if_done` | string | No | Downside risk of acting |
| `risk_if_not_done` | string | No | Downside risk of inaction |
| `dependencies` | [string] | No | Dependent action IDs |
| `operator_decision_required` | bool | No | Default `true` |
| `deadline` | ISO8601 | No | Must-act-by timestamp |
| `expiry` | ISO8601 | No | Action expires after this time |
| `next_check_at` | ISO8601 | No | Follow-up check timestamp |
| `followup_condition` | string | No | Human-readable condition |
| `source_snapshot_id` | string | No | Source data snapshot |
| `source_hash` | string | No | Hash of source data |
| `specialist_artifact_refs` | [string] | No | Specialist output references |
| `cio_artifact_id` | string | No | Associated CIO artifact |
| `origin_run_id` | string | No | Run that generated this action |
| `legacy_cio_decision_id` | int | No | Back-reference to legacy DB row |
| `idempotency_key` | string | No | Deterministic deduplication key |

---

## 3. State Machine

```
                    ┌─────────┐
                    │  OPEN   │◄────────────────────┐
                    └────┬────┘                      │
          ┌──────────────┼──────────────┐            │
          ▼              ▼              ▼            │
   ┌─────────────┐ ┌───────────┐ ┌──────────┐       │
   │ACKNOWLEDGED │ │ EVIDENCE  │ │FOLLOWUP  │       │
   └──────┬──────┘ │ ATTACHED  │ │SCHEDULED │       │
          │        │ (no-op on │ │(no-op on │       │
          │        │  status)  │ │ status)  │       │
          ├────────┴───────────┴───────────┤       │
          ▼              ▼              ▼          │
   ┌──────────┐   ┌──────────┐   ┌──────────┐      │
   │ DEFERRED │   │  DONE    │   │ EXPIRED  │      │
   └────┬─────┘   └────┬─────┘   └────┬─────┘      │
        │              │              │            │
        │              ▼              ▼            │
        │       ┌─────────────┐ ┌───────────┐     │
        │       │ SUPERSEDED  │ │ CANCELLED │     │
        │       └─────────────┘ └─────┬─────┘     │
        │                             │           │
        └──────────┬──────────────────┘           │
                   ▼                              │
            ┌──────────┐                          │
            │ BLOCKED  │──► UNBLOCKED ────────────┘
            └──────────┘
```

### Allowed Transitions

| From | To |
|---|---|
| `OPEN` | `ACKNOWLEDGED`, `DEFERRED`, `DONE`, `EXPIRED`, `SUPERSEDED`, `CANCELLED`, `BLOCKED`, `EVIDENCE_ATTACHED`, `FOLLOWUP_SCHEDULED`, `OPERATOR_DECISION_RECORDED` |
| `ACKNOWLEDGED` | `DEFERRED`, `DONE`, `EXPIRED`, `SUPERSEDED`, `CANCELLED`, `BLOCKED`, `EVIDENCE_ATTACHED`, `FOLLOWUP_SCHEDULED`, `OPERATOR_DECISION_RECORDED` |
| `DEFERRED` | `OPEN`, `DONE`, `EXPIRED`, `SUPERSEDED`, `CANCELLED`, `BLOCKED` |
| `BLOCKED` | `OPEN` (via `UNBLOCKED`), `CANCELLED`, `EXPIRED`, `SUPERSEDED` |
| `DONE`, `EXPIRED`, `CANCELLED` | `SUPERSEDED` only |

**Terminal statuses:** `DONE`, `EXPIRED`, `SUPERSEDED`, `CANCELLED`

**Policy:** Terminal actions may only be superseded (CI-2). All other
transitions from terminal states are rejected with `ValueError`.

### Canonical Event Types

1. `CIO_ACTION_CREATED` — New action → `OPEN`
2. `CIO_ACTION_ACKNOWLEDGED` — Operator acknowledged → `ACKNOWLEDGED`
3. `CIO_ACTION_DEFERRED` — Action deferred → `DEFERRED`
4. `CIO_ACTION_DONE` — Action completed → `DONE`
5. `CIO_ACTION_EXPIRED` — Deadline exceeded → `EXPIRED`
6. `CIO_ACTION_SUPERSEDED` — Replaced by newer action → `SUPERSEDED`
7. `CIO_ACTION_CANCELLED` — Operator cancelled → `CANCELLED`
8. `CIO_ACTION_BLOCKED` — health_boundary block → `BLOCKED`
9. `CIO_ACTION_UNBLOCKED` — Block cleared → `OPEN`
10. `CIO_ACTION_FOLLOWUP_SCHEDULED` — Follow-up scheduled (non-status-modifying)
11. `CIO_ACTION_EVIDENCE_ATTACHED` — Evidence appended (non-status-modifying)
12. `CIO_ACTION_OPERATOR_DECISION_RECORDED` — Operator recorded decision (non-status-modifying)
13. `CIO_ACTION_LEDGER_GENESIS` — Ledger initialization (housekeeping)

---

## 4. Storage Architecture

```
data/cio/
  cio_action_ledger.jsonl       # Canonical append-only event log (authoritative)
  cio_action_ledger.jsonl.lock  # fcntl lock file (auto-created)
```

- **Single JSONL file** — one event per line, newline-delimited.
- **Sort keys, compact JSON** — `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- **fcntl LOCK_EX** — exclusive write lock per append; all writers serialize.
- **fsync** — every append calls `os.fsync()` before releasing the lock.
- **No full-file rewrite** — O_APPEND only; the file grows monotonically.

---

## 5. Hash Chain Design

```
genesis ──► event_1 ──► event_2 ──► ... ──► event_N
 prev=0      prev=H(g)   prev=H(e1)          prev=H(eN-1)
 hash=H(g)   hash=H(e1)  hash=H(e2)          hash=H(eN)
```

- **SHA-256** throughout.
- `prev_event_hash` chains globally (all events, all streams, one chain).
- `payload_hash` is a SHA-256 of the canonicalized payload.
- `event_hash` is a SHA-256 of the full envelope minus `event_hash`.
- `verify_integrity()` replays the entire file checking all three hash
  guarantees and reports any chain breaks or hash mismatches.
- The hash chain is **independent of `file_integrity.py`**: the latter is
  a separate per-file manifest system; the ledger's chain is self-contained.

**Canonical serialization:** `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.  This guarantees deterministic hashing regardless of dict insertion order.

---

## 6. Idempotency Strategy

- **Key:** `idempotency_key` field in the action/payload dict.
- **Strategy:** Before creating or transitioning, search the event stream for
  an event whose `payload.idempotency_key` matches. If found, return the
  existing event.
- **Scope:** Per-stream (searches only events in the same `cio_action_id`).
- **Idempotent create:** The idempotency check runs **before** validation,
  so duplicate-create requests return the original event instead of raising.
- **Concurrent safety:** Under the fcntl lock, the hash chain head is
  re-determined; for paranoia, re-check idempotency inside the lock.

---

## 7. Write Authority Rules

| Actor | Authority | Allowed Operations |
|---|---|---|
| `alex` (agent) | `advisory` | `CIO_ACTION_CREATED`, `EVIDENCE_ATTACHED`, `FOLLOWUP_SCHEDULED`, `SUPERSEDED` |
| `operator` | `operator` | All transitions including `ACKNOWLEDGED`, `DONE`, `CANCELLED`, `DEFERRED`, `OPERATOR_DECISION_RECORDED` |
| `system` | `system` | `CIO_ACTION_BLOCKED`, `CIO_ACTION_UNBLOCKED`, `CIO_ACTION_LEDGER_GENESIS`, `CIO_ACTION_EXPIRED` |

**Currently enforced:** Actor type validation. Full per-event-type authority
matrix enforcement is deferred to P-1.4 (Governed Model Bridge integration).

**Alex's model:** Alex cannot call `CIOActionLedger.create_action()` directly.
Alex must route through `create_cio_action()` (the public API gate) which
validates actor authorization and assigns the correct authority level.

---

## 8. Projection Design

Projections are **in-memory, derived on read via event replay**.

- `get_action(cio_action_id)` → Replays the event stream for that ID,
  folding each event into a current-state dict.
- `list_actions(status=?, domain=?)` → Scans all stream IDs, replays each,
  filters, and returns.
- Projections are **NEVER written** to a separate file. The event log is
  the only durable state.
- Performance: acceptable for LAB phase (< 1000 events). Future P-2.x
  may add snapshot caching.

### Projected Fields

`get_action` returns a dict with all CREATE payload fields plus:
- `current_status` — derived from the last status-transition event
- `event_count` — total events in the stream
- `last_event_id` — most recent event ID
- `last_event_hash` — most recent event hash
- `created_at` / `updated_at` — timestamps from events
- `operator_decision` / `operator_decision_at` — operator action record

---

## 9. Recovery / Crash Procedures

### Crash After fsync

Every append calls `os.fsync()`. If the process crashes after fsync but
before returning the event dict, the event is **fully durable** on disk.
A fresh `CIOActionLedger()` instance will:
1. Read the genesis or last event from the file.
2. Continue appending from the correct chain head.
3. `get_action(cio_action_id)` will replay and surface the event.

**Test:** `test_crash_after_fsync_no_effect` — writes event, reads raw file,
opens a new ledger instance, confirms the action is projected correctly.

### Hash Chain Corruption

`verify_integrity()` detects:
- Invalid JSON lines
- Payload hash mismatches (tampered payloads)
- Event hash mismatches (tampered envelopes)
- Chain breaks (missing or reordered events)

**Response:** If corruption is detected, the ledger raises alerts but does
**not** auto-patch or rewrite. The operator is notified (P-1.7).

### Rollback

To disable the ledger service:
1. Stop the process that owns the ledger.
2. Keep the JSONL file preserved for audit.
3. Switch `ALEX_CIO_ACTION_LOG` env or config flag to point to `/dev/null`.

---

## 10. Integration Points

| Phase | Integration | Status |
|---|---|---|
| **P-1.4** | Governed Model Bridge — Alex's LLM calls `create_cio_action()` and `transition_action()` through the governed bridge | `p_1_4_ready: true` |
| **P-1.5** | health_boundary — `CIO_ACTION_BLOCKED` / `CIO_ACTION_UNBLOCKED` events triggered by data quality checks | Not implemented |
| **P-1.7** | Telegram Outbox — operator notifications on new/blocked actions | Not implemented |
| **P-2.x** | PostgreSQL migration — swap JSONL for a PostgreSQL event-store table with hash-chain guarantees | Not implemented |

---

## 11. Future PostgreSQL Path

When scaling demands exceed in-memory replay:
1. Create a `cio_action_events` table with identical schema fields plus a
   monotonically-increasing `seq` column.
2. Migrate all JSONL lines via `COPY` (preserves insertion order).
3. Keep hash-chain verification as an integrity check after migration.
4. Replace `list_events()` with `SELECT … WHERE stream_id = ? ORDER BY seq`.
5. Projections can use `LAST_VALUE` window functions or materialized views.

---

## 12. Rollback

**Preserve event file, disable service:**

```bash
# Stop any process writing to the ledger
pkill -f cio_action_ledger

# Preserve the event log
cp data/cio/cio_action_ledger.jsonl data/cio/cio_action_ledger.jsonl.bak.$(date +%Y%m%d)

# To disable: remove the module or set an env flag
export CIO_ACTION_LEDGER_DISABLED=true
```

**Re-enable:** Remove the env flag and restart.
