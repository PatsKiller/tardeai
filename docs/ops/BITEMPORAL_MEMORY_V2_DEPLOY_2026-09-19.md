# Bitemporal Memory Substrate v2 — deploy receipt

Status: ACTIVE (isolated only)
as_of: 2026-09-19T17:40:00Z
Measured at: worktree cursor/aec-rail-full-667c + Docker tradeai-m2-shadow-v2 :55432
Canonical repo path: sql/trade-ai-bitemporal-schema-v2.sql
Authority: READ_ONLY_ADVISORY / MBI_BEHAVIOR=0
Supersedes: none (packages existing sql/r10_m2_isolated_benchmark.sql)
See also: docs/ops/TRADE_AI_M2_MEMORY_SUBSTRATE_BENCHMARK_2026-08-24.md, AGENTS.md §7 identity spine

## Deploy (isolated — production :5432 refused)

- Container: `tradeai-m2-shadow-v2` (pgvector/pgvector:pg16) on `127.0.0.1:55432`
- Applied: `sql/r10_m2_isolated_benchmark.sql` + `sql/trade-ai-bitemporal-schema-v2.sql`
- Verified tables/views: MemoryIdentity@v1, MemoryFactVersion@v2, AdjudicationReceipt@v1, ProvenanceEdge@v1
- Verified functions: `save_bitemporal_fact_version` (alias), `write_fact_version`, `block_bitemporal_manipulation`, `trg_block_fact_manipulation`
- Verified exclusion: `fact_single_valued_current_excl` (GiST, CURRENT + SINGLE_VALUED_CURRENT)
- `production_sql_applied`: **false**

## Integration

- `scripts/lib/cio_memory_integration.py` — `CIOEnvelopeIntegrator`
- CLI: `scripts/cio_memory_integration.py --dry-run|--apply|--apply-schema`
- Package path: `trade_ai.memory` re-exports (no duplicate writer)
- AEC cycle dry-runs cognitive envelope on every cycle (apply=False)

## Correctness

- `tests/test_bitemporal_correctness.py`: **211 passed**
  - 200-case in-process oracle
  - a–e Docker categories (exclusion, multi-valued, version closure, RLS via m2_agent, audit immutability)
- EXPLAIN (ANALYZE, BUFFERS): **Index Scan** on `fact_valid_spgist` (not Seq Scan); Shared Hit Blocks; 0 disk reads

## Constitutional rails observed

- Financial keys refused (`FINANCIAL_TRUTH_REFUSED`)
- GUID spine linkage on identity rows
- DB-owned `tx_period` via SECURITY DEFINER writer
- Composite `(tenant_id, guid)` + FORCE RLS (proven as non-superuser `m2_agent`)


## Studio 200-case matrix (2026-09-19)

`tests/test_bitemporal_correctness.py` implements Suites 1–5 (200 docker cases + rails).
Measured: **205 passed** against `tradeai-m2-shadow-v2` `:55432`.
CI: `.github/workflows/bitemporal-memory-correctness-ci.yml` (service port **55432 only**; production `:5432` DSN refused).
Reconciled: `row_kind` → `upper_inf(tx_period)`; `app.current_tenant` → `app.tenant_id`.

## Production cutover attempt — 2026-09-19T20:34 ET (BLOCKED, nothing applied)

Operator granted the `:5432` cutover. It **could not be executed**. A probe transaction was
run against the live `trade_ai` database and **rolled back**; `production_sql_applied`
remains **false** and production is unchanged.

Measured on production (PostgreSQL **17.10**, satisfies ≥14):

| probe | result |
|---|---|
| `CREATE EXTENSION btree_gist` | OK (trusted in PG17) |
| `CREATE EXTENSION pgcrypto` | OK |
| `CREATE EXTENSION "uuid-ossp"` | OK |
| `CREATE EXTENSION vector` | **BLOCKED — extension "vector" is not available** |
| `CREATE ROLE m2_agent` | **BLOCKED — permission denied to create role** |
| `CREATE SCHEMA` | OK (`trade_ai` holds CREATE on database) |

`trade_ai` is `rolsuper=f, rolcreatedb=f, rolcreaterole=f`. Schema `memory_r10_m2` is absent
from production; only `plpgsql` is installed.

**Prerequisites for a retry (both need superuser / OS access):**

1. Install pgvector on the production host (e.g. `postgresql-17-pgvector`) and
   `CREATE EXTENSION vector` — `memory_fact_version.embedding` and the
   `write_fact_version(...)` signature both require type `vector`.
2. Create role `m2_agent` (or grant `CREATEROLE` to `trade_ai`). Do **not** reuse the
   shadow's `m2agent` literal password in production.

**Hazard:** `sql/r10_m2_isolated_benchmark.sql:9` is
`DROP SCHEMA IF EXISTS memory_r10_m2 CASCADE;`. Harmless on first production apply (schema
absent) and on the rebuilt shadow, but **destructive on re-run**. Guard or split it before
applying to `:5432`.

Correctness re-run on the shadow at this measurement: **205 passed in 3.13s**.

## 2026-09-20 — destructive-reset guard + corrected pgvector path

**Hazard fixed.** `sql/r10_m2_isolated_benchmark.sql` no longer drops unconditionally. The
`DROP SCHEMA IF EXISTS memory_r10_m2 CASCADE` now runs only when the session sets
`m2.allow_destructive_reset = 'on'`; if the schema exists and the flag is unset, the file
raises `M2_DESTRUCTIVE_RESET_REFUSED` and changes nothing. A manual or production
`psql -f` therefore cannot wipe live cognitive memory by re-running the file.

All three in-repo appliers set the flag explicitly and each sits behind an isolated-DSN
assertion:

| applier | isolation |
|---|---|
| `memory_m2_benchmark.apply_schema` | `connect()` → `_assert_isolated_dsn` |
| `memory_m2_v2.apply_schema` | `connect()` → `_assert_isolated_dsn` |
| `cio_memory_integration.apply_bitemporal_schema_v2` | **new** `_assert_isolated_conn` (refuses port 5432) |

The third previously only claimed "Isolated DSN only" in its docstring while accepting any
caller-supplied connection — that claim is now enforced rather than asserted.

Suite: **206 passed** (was 205; `test_schema_file_refuses_destructive_reset_without_optin`
asserts the refusal, that the schema survives it, and that an opted-in rebuild still works).

**pgvector path corrected.** The earlier note suggested `postgresql-17-pgvector`. That
package **does not exist** in the configured Ubuntu repos — `apt-cache search pgvector`
returns only `postgresql-18-pgvector`, while production is the PG **17** cluster
(`pg_lsclusters`: `17/main` on `:5432`, the only cluster). `postgresql-server-dev-17` has no
candidate either and no PGDG repo is configured, so building from source does not avoid the
repo addition. The supported route is to add the PGDG apt repo, which ships
`postgresql-17-pgvector` — see `docs/remediation-plan.md` § "Getting pgvector onto PG17".

`production_sql_applied` remains **false**. Both cutover prerequisites still need operator
action with superuser / OS access.
