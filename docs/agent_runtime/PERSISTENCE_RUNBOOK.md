# Agent-runtime persistence slice — runbook

Scope: the production-inactive PostgreSQL persistence / concurrency / replay slice for
the governed agent runtime (MVL). LAB/SHADOW only. No broker, order, approval, 2FA,
scheduler, service, provider, or config-promotion authority is added or activated.

## Components

| File | Purpose |
| --- | --- |
| `scripts/agent_runtime/persistence.py` | `RunPersistence` protocol; `InMemoryPersistence` (hermetic reference) and `PostgresPersistence` (authoritative eight-table backend over an **injected** DB-API connection). Shared template-method base owns all semantics so both backends agree. |
| `scripts/agent_runtime/export_replay.py` | Deterministic JSONL export, model-free replay, and tamper detection over the run hash chain. |
| `migrations/agentic_runtime/0001_mvl.up.sql` / `0001_mvl.down.sql` | The reviewed eight-table schema (unchanged by this slice). |
| `tests/test_agent_runtime_persistence.py` | Behavioral suite run against **both** backends + Postgres SQL/transaction contract + optional real-LAB roundtrip. |
| `tests/test_agent_runtime_export_replay.py` | Export determinism, replay, and tamper detection. |

## Why the driver is injected

The focused CI authority scan forbids `import psycopg2` (and `subprocess`, `requests`,
`keyring`, `bw`) anywhere in `scripts/agent_runtime`. `PostgresPersistence` therefore
accepts a DB-API 2.0 connection created by the operator/caller and never imports a
driver. This is also the cleaner architecture the assignment asks for: an explicit
persistence protocol and a Postgres implementation instead of SQL scattered through
orchestration code.

## Connecting at runtime (LAB/SHADOW)

The runtime credential may reach **only** `agentic_runtime`. The migration identity is
never used at runtime. Example (operator-supplied connection, secrets never in repo):

```python
import psycopg2  # created OUTSIDE scripts/agent_runtime
from scripts.agent_runtime.persistence import PostgresPersistence

conn = psycopg2.connect(
    host="/home/johnclaw/tradeai-lab/sock", port=5433,
    dbname="trade_ai_agentic_lab", user="agentic_runtime_lab_rw",
    options="-c search_path=agentic_runtime",
)
store = PostgresPersistence(conn)
store.assert_runtime_only()   # fail-closed if connected as the migration identity
```

Never connect on port 5432 (production). The migrator role (`agentic_lab_migrator`)
runs migrations only and must never be a runtime credential.

## Invariants enforced (application + database)

- **Append-only**: runs are the one mutable control row; artifacts/tool-calls/reviews/
  scores/lessons/cases/chunks are append-only (DB triggers + adapter never issues
  UPDATE/DELETE on them).
- **Monotonic, non-forking journal**: each append advances a per-run `sequence` and a
  SHA-256 hash chain, serialized by `SELECT ... FOR UPDATE` on the run row (in-memory:
  a per-run lock). Concurrent appends cannot fork the chain.
- **Idempotency by stable identity**: artifacts key on `UNIQUE (run_id, payload_hash)`;
  tool-calls/reviews/scores use deterministic ids (`derive_id(...)`), so a duplicate
  submission is a no-op — never a random UUID with an ineffective `ON CONFLICT`.
- **Producer separation**: self-review and self-score are rejected in application logic
  *and* by the `producer <> reviewer/scorer` DB CHECKs. There is no self-review path.
- **No secrets**: every payload passes `assert_no_secret_material` before persistence;
  export additionally rejects any connection metadata.
- **Terminal enforcement**: COMPLETED/CANCELLED/FAILED runs never mutate again and never
  resume; a new run needs a new immutable envelope.
- **Fail-closed writes**: every write runs in an explicit transaction with a bounded
  `statement_timeout`; any failure rolls back and raises `PersistenceError` — a failed
  step is never reported as a completed checkpoint or a successful artifact.

## Export / replay / tamper detection

- `export_run_jsonl(store, run_id)` → stable, canonical-JSON event lines (byte-compatible
  with the in-memory `ShadowRunJournal`), excluding secrets and connection metadata.
- `export_manifest(store, run_id)` → schema/journal-contract versions, `event_count`,
  `head_hash`.
- `replay_jsonl(lines)` → run state folded from events, with **no** model/provider call.
- `verify_jsonl(lines, manifest=...)` → detects missing, reordered, duplicated or
  modified records from the chain, and truncated tails via the manifest.

## LAB DB proof (Phase A gate)

The exact-ref proof runs against the isolated LAB cluster on 5433 only and must print
`final_status|PASS_DB_PROOF`. It never touches port 5432. It is not run automatically;
it does not self-teardown — clear the disposable LAB with the packet-generated
`agentic-runtime-rollback-*.sql` before re-running.

## Rollback

- Code: revert this branch's commits; the migration and schema are unchanged.
- LAB DB: run the packet's generated rollback SQL (drops the disposable `trade_ai_agentic_lab`
  database and its three roles). Production is never touched.
