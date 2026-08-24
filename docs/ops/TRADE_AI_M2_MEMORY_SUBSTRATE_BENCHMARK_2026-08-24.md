# M2 memory substrate benchmark

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED (isolated). Not MERGED as live. Not applied to production.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

Isolated Docker only: `127.0.0.1:55432` container `tradeai-m2-shadow` (`pgvector/pgvector:pg16`). Production `:5432` is refused by the harness.

## Lanes

| lane | substrate | result |
|---|---|---|
| A | native Trade AI Postgres bitemporal (`memory_r10_m2`) | MEASURED |
| B | native + pgvector 0.8.6 (HNSW + IVFFlat indexes created) | MEASURED |
| C | pgmnemo **v0.20.0** (current stable, GitHub/PGXN 2026-08-20) | UNMEASURED_INSTALL — extension not on image; operational complexity HIGH |

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

**POSTGRES_PGVECTOR**

Reasons: Lane A bitemporal + tenant invariants hold; Lane B adds optional vectors without Titan/HNSW mandate; Lane C current-stable pgmnemo is not installable without compiling into the image (complexity HIGH, no quality number).

`BYPASSRLS` / `SECURITY DEFINER` / pool reuse: **UNMEASURED** (called out, not faked).

## Production

`sql/r10_memory_shadow.sql` and `sql/r10_m2_isolated_benchmark.sql` were **not** applied to production.
