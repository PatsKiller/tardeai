# Agent-runtime persistence slice — runbook

Scope: the production-inactive PostgreSQL persistence / concurrency / replay slice for
the governed agent runtime (MVL). LAB/SHADOW only. No broker, order, approval, 2FA,
scheduler, service, provider, or config-promotion authority. Never contacts production
port 5432.

## Components

| File | Purpose |
| --- | --- |
| `scripts/agent_runtime/persistence.py` | `RunPersistence` protocol; `InMemoryPersistence` (copy-on-write reference) and `PostgresPersistence` (authoritative eight-table backend over an injected **connection factory**). A template-method base owns all semantics so both backends agree. |
| `scripts/agent_runtime/export_replay.py` | Deterministic JSONL export, manifest-authoritative replay, tamper detection. |
| `scripts/agent_runtime/host_proof_from_ref.sh` | Exact-ref host-proof wrapper: evolves a fresh LAB on 5433, runs the real psycopg2 suite non-skipping (incl. two-connection concurrency), tears down, emits `final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF`. |
| `tests/test_agent_runtime_persistence.py` | Behavioral suite on **both** backends + Postgres SQL/transaction contract. |
| `tests/test_agent_runtime_export_replay.py` | Export/replay + tamper + hostile-JSON. |
| `tests/test_agent_runtime_real_postgres.py` | Real LAB proof (skips unless `AGENTIC_REAL_LAB=1`; run by the wrapper). |

## Design corrections (this slice)

- **Persisted-truth binding.** Idempotent `create_run` compares the *complete* immutable
  envelope + budget; a changed field raises `IdempotencyConflictError`. Reviews/scores
  load the **persisted** artifact and take its run and producer from the row — a caller
  cannot assert a false producer to bypass no-self-review/score. An artifact payload-hash
  conflict returns the already-persisted id.
- **Append-only journal.** Run events are immutable rows in `agent_artifacts` (reserved
  `__run_event__` type), each with a per-run sequence and previous-hash chain keyed by its
  own event hash and protected by the migration's append-only trigger. Mutable
  `agent_runs.checkpoint` is only a pointer; `reconstruct`/`journal` validate the chain
  from the immutable rows, so history cannot be silently rewritten. No migration change.
- **Durable tool lifecycle.** proposed / decision / started / terminal are separate durable
  events; a crash mid-call leaves reconstructable in-flight evidence.
- **Transactional concurrency.** One connection + one transaction per operation (autocommit
  off), bounded `statement_timeout`, parameterized SQL, `SELECT ... FOR UPDATE` on the run
  row before advancing its chain. The in-memory backend is copy-on-write, so both roll back
  identically with no partial state.
- **Runtime identity.** Verified automatically before the first write: `current_user` must be
  in an explicit LAB/SHADOW writer allowlist and must NOT hold
  superuser/createdb/createrole/replication/bypassrls. The migration identity is never used.
- **Completion prerequisites.** `complete_run` requires ≥1 material artifact and ≥1
  independent review; terminal runs never resume or mutate execution state — but independent
  post-run Darwin scoring is allowed (append-only).
- **Replay integrity.** Authoritative `replay_jsonl` requires a trusted manifest; `verify_jsonl`
  rejects missing / reordered / duplicated / modified / truncated / mixed-run /
  unknown-contract / malformed streams and never raises on hostile JSON.
- **Knowledge base.** `record_lesson` / `record_case` / `record_chunk` — deterministic ids,
  append-only, provenance + source hashes, temporal validity, lifecycle validation, no
  self-ratification, no secrets, idempotent, conflict-rejecting. No automatic promotion.

## Connecting at runtime (LAB/SHADOW)

`PostgresPersistence` takes a zero-arg connection factory; the driver is never imported here.

```python
import psycopg2  # created OUTSIDE scripts/agent_runtime
from scripts.agent_runtime.persistence import PostgresPersistence

def factory():
    return psycopg2.connect(host="/home/johnclaw/tradeai-lab/sock", port=5433,
                            dbname="trade_ai_agentic_lab", user="agentic_runtime_lab_rw",
                            options="-c search_path=agentic_runtime")  # autocommit off

store = PostgresPersistence(factory)  # runtime identity verified automatically before writes
```

Never connect on port 5432. The migrator role (`agentic_lab_migrator`) runs migrations only.

`MvlRuntime(..., persistence=store)` records run identity durably via the protocol while
`ShadowRunJournal` stays the in-memory compatibility/replay backend.

## Host proof (run by the integrator, not in CI)

```bash
REPO=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild \
AGENTIC_SOURCE_REF=<corrected 40-char SHA> \
bash scripts/agent_runtime/host_proof_from_ref.sh
```

Emits `source_commit`, `database_port|5433`, `production_port_5432_contact|NONE`, per-property
`PASS` markers, `activation_authority|DENIED`, `production_database_write|NONE`, and
`final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF`, then tears the LAB down (or prints the
exact rollback path on failure). Prints no passwords, DSNs, tokens, or connection metadata.

## Rollback

- Code: revert this branch's commits; the migration and schema are unchanged.
- LAB DB: run the packet-generated `agentic-runtime-rollback-*.sql` (drops the disposable
  `trade_ai_agentic_lab` database and its roles). Production is never touched.
