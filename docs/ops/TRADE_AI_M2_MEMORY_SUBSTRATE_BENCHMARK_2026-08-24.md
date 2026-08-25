# M2 memory substrate benchmark

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED + MERGED (#498 `0e1ad9d9`) + BENCHMARKED isolated. **Not SHADOW. Not PRODUCTION.**  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  
**production_sql_applied:** false  

Isolated Docker only: `127.0.0.1:55432` container `tradeai-m2-shadow` (`pgvector/pgvector:pg16`, Postgres 16.15). Production `:5432` is refused by the harness (`M2_DSN_PRODUCTION_PORT_FORBIDDEN`). No startup hook, deployment hook, or migration applies this SQL.

v2 schema (Google Notes harmonized): built-in `tstzrange` periods, DB-owned `tx_period` via `write_fact_version()`, `CURRENT = upper_inf(tx_period)`, `PredicateTemporalPolicy`, GiST exclusion **only** for `SINGLE_VALUED_CURRENT`, FORCE RLS, non-owner `m2_agent` (`NOSUPERUSER` / `NOBYPASSRLS`), normalized `provenance_edge` and `AdjudicationReceipt@v1`.

## Lanes (three-lane bake-off)

R10.7 required: do **not** call a winner while pgmnemo is `UNMEASURED_INSTALL`. Path A was taken — pgmnemo v0.20.0 was installed **only** in the isolated container (control files present; `CREATE EXTENSION` succeeded). Official pgmnemo CI is PG17-blocking / 14–16 aspirational; isolated PG16.15 still loaded 0.20.0.

| lane | substrate | result |
|---|---|---|
| A | native Trade AI Postgres bitemporal (`memory_r10_m2`) | **MEASURED** |
| B | native + pgvector 0.8.6 (HNSW + IVFFlat indexes created) | **MEASURED** |
| C | pgmnemo **v0.20.0** | **MEASURED** (not DISQUALIFIED, not UNMEASURED_INSTALL) |

Lane C ingest/BM25 recall: `lesson_id` returned, `recall_rows=3`. It is a **lesson corpus**, not MemoryFact@v2:

- `vector(1024)` vs LOCAL_ONLY nomic `vector(768)`
- `project_id` int / topic text vs issuer/security/listing GUID spine
- `t_valid_from/to` vs `tstzrange`
- no composite tenant FK, no SINGLE_VALUED_CURRENT exclusion

`viable_as_canonical_fact_store = false`.

No Neo4j installed. Multi-hop graph requirements were not failed by Postgres; `NEO4J_SHADOW_POC_JUSTIFIED` is **not** met. `neo4j_decision = POSTGRES_SUFFICIENT`.

## Storage decision

**POSTGRES_PGVECTOR** — `provisional=false`.

Allowed only because every viable lane is MEASURED or FORMALLY_DISQUALIFIED. Lane C is MEASURED and is **not** the canonical fact store.

This is an architectural/benchmark decision. It is **not** production cutover authority. Shadow-write / parity / restore / natural-read / rollback is a later program (`M2_PRODUCTION_SHADOW_MIGRATION_DESIGN`).

## Transaction-time contract

Selected: **`statement_timestamp()` + `version_seq`**.

Rejected as sole order key:

- caller-authored `tx_from` (caller could backdate)
- `transaction_timestamp()` for multi-write transactions (collapses distinct version events)
- `clock_timestamp()` as sole order (NTP/jitter; not collision-safe)

Required properties: database-owned, caller cannot backdate `tx_period`, replay order deterministic via `version_seq`, same logical statement remains auditable.

## Correctness (isolated remeasure 2026-08-24 20:09 ET)

- Golden 200 in-process oracle: 200/200, Recall@1=1.0 (**not** LongMemEval live retrieval quality)
- Cross-tenant read leakage: **0**; missing tenant fail-closed; FORCE RLS on
- `m2_agent` wrote via `write_fact_version`; direct INSERT blocked; `bypassrls=false`
- SINGLE_VALUED_CURRENT overlap rejected; MULTI_VALUED opinions allowed
- Similarity remains `CANDIDATE`; cosine cannot self-ratify
- Titan / cloud embeddings: DISABLED
- HNSW / 10× over-fetch / 0.75 threshold: **not** architectural mandates (indexes created for measurement only)

## Scale / plans

| dataset | status |
|---|---|
| 1k versions | MEASURED (~5.8s write, ~4.8ms current read) |
| 10k versions | MEASURED (~56s write, ~45ms current read) |
| 100k | **NOT_RUN** |
| 1M | **NOT_RUN** |

EXPLAIN (ANALYZE, BUFFERS) on isolated data: Index Scan on `fact_current_idx` / `fact_valid_spgist` / `fact_tx_gist`. Shared hits, 0 disk reads at this volume. **Do not claim a winner from trivial volume for 100k/1M — those were not run.**

Pool-reuse BYPASSRLS / extra SECURITY DEFINER routes beyond `write_fact_version`: still only partially measured (`m2_agent` path measured).

## Production

`sql/r10_memory_shadow.sql` and `sql/r10_m2_isolated_benchmark.sql` were **not** applied to production `:5432`. No dual writer. Application code does not silently read the shadow.
