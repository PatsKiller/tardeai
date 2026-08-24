# Bitemporal memory data model

**Date:** 2026-08-24  
**Status:** DESIGNED + IMPLEMENTED_SOURCE + TESTED. Not MERGED as live. Not LIVE. Not NATURALLY_PROVEN.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

Memory is NON_AUTHORITATIVE_CONTEXT. Ticker remains an alias. `subject_guid` must be an existing issuer/security/listing/entity GUID.

## Intervals

Closed-open:

- `[valid_from, valid_to)` — when the fact was true in the world
- `[tx_from, tx_to)` — when the system knew it (assigned by the persistence layer)

LLMs must not author authoritative dates.

## Query modes

| mode | meaning |
|---|---|
| AS_KNOWN_NOW | valid and tx at now |
| AS_KNOWN_AT(tx_at) | what the system knew at tx_at |
| VALID_AT(valid_at) | facts true at valid_at as known now |
| VALID_AT_AND_KNOWN_AT(valid_at, tx_at) | time travel |

## SIX_ARCHITECTURAL_CORRECTIONS

1. **Local-first embeddings.** Default `LOCAL_ONLY` (`nomic-embed-text` / 768 / loopback). Amazon Titan and other cloud embeddings are `DISABLED_BY_DEFAULT`. Generative local LLMs are forbidden on the memory path.
2. **No Neo4j mandate.** Postgres SHADOW DDL exists. `NEO4J_SHADOW_POC_DECISION=INSUFFICIENT_DATA` until relational/CTE/pgvector benchmarks exist on real queries.
3. **No HNSW mandate.** Vector index recommendation is `INSUFFICIENT_DATA`. Exact cosine is the only measured synthetic check.
4. **Similarity is not an edge.** `SimilarityCandidate@v1` cannot self-ratify at cosine 0.75 or 0.99.
5. **Logical tenant isolation, not hardware isolation.** `tenant_id NOT NULL`. Unscoped queries fail closed. RLS is DESIGNED for shadow, not production-activated here.
6. **No private chain-of-thought.** Persist `DecisionRationale@v1` only.

## SHADOW

`sql/r10_memory_shadow.sql` — do not apply to production in this PR. In-memory `MemoryFactStore` is the test double.

M1 baseline curation remains a separate MERGE_CANDIDATE (#494). This PR does not rewrite it.
