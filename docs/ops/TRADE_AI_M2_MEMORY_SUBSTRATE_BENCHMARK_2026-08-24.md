# M2 memory substrate benchmark

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED (isolated). Not MERGED as live. Not applied to production.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

Isolated Docker only: `127.0.0.1:55432` container `tradeai-m2-shadow` (`pgvector/pgvector:pg16`). Production `:5432` is refused by the harness.

v2 schema (Google Notes harmonized): built-in `tstzrange` periods, DB-owned `tx_period` via `write_fact_version()`, `CURRENT = upper_inf(tx_period)`, `PredicateTemporalPolicy`, GiST exclusion **only** for `SINGLE_VALUED_CURRENT`, FORCE RLS, non-owner `m2_agent`, normalized `provenance_edge`.

## Lanes

| lane | substrate | result |
|---|---|---|
| A | native Trade AI Postgres bitemporal (`memory_r10_m2`) | MEASURED |
| B | native + pgvector 0.8.6 (HNSW + IVFFlat indexes created) | MEASURED |
| C | pgmnemo **v0.20.0** (current stable) | **MEASURED** isolated: CREATE EXTENSION + ingest/BM25 recall. Not a MemoryFact@v2 store (`vector(1024)`, `project_id` int, `t_valid_from/to`). |

No Neo4j installed. Multi-hop graph requirements were not failed by Postgres; `NEO4J_SHADOW_POC_JUSTIFIED` is **not** met.

## Correctness

- Closed-open `[valid_from, valid_to)` / `[tx_from, tx_to)`
- Composite FK `(tenant_id, identity_id)` plus **FORCE ROW LEVEL SECURITY**
- Cross-tenant read leakage: **0**
- Missing tenant fail-closed: **true**
- Exclusive CURRENT (one open tx interval) with losing evidence on `AdjudicationReceipt@v1`
- Similarity remains `CANDIDATE`; cosine cannot self-ratify
- Titan / cloud embeddings: DISABLED
- HNSW / 10× over-fetch / 0.75 threshold: **not** architectural mandates
- Local nomic-embed-text: BUSY_OR_UNMEASURED this run (Ollama pending-request cap)

## Golden 200

In-process oracle `Recall@1 = 1.0` (200/200). This is **not** LongMemEval live retrieval quality.

## Storage decision

**POSTGRES_PGVECTOR** (non-provisional: Lane C is MEASURED, not UNMEASURED_INSTALL)

Reasons: Lane A/B satisfy Trade AI MemoryIdentity/MemoryFactVersion (tstzrange, composite tenant FK, DB-owned `statement_timestamp()+version_seq`, FORCE RLS). Lane C pgmnemo v0.20.0 **is installed and BM25-recalls** on isolated PG16.15, but it is a lesson corpus (`agent_lesson`, `vector(1024)`, integer `project_id`) and does **not** implement the issuer/security/listing GUID spine or SINGLE_VALUED_CURRENT exclusion. Therefore it is not the canonical fact store.

Tx-time contract: `statement_timestamp()` plus `version_seq`. Callers cannot backdate `tx_period`.

`BYPASSRLS` / `SECURITY DEFINER` / pool reuse: **UNMEASURED** (called out, not faked).

## Production

`sql/r10_memory_shadow.sql` and `sql/r10_m2_isolated_benchmark.sql` were **not** applied to production.
