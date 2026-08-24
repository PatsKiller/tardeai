# Memory retrieval and index strategy

**Date:** 2026-08-24  
**Status:** DESIGNED + IMPLEMENTED_SOURCE + TESTED (harness). Index type: **UNMEASURED**.  
**Authority:** `READ_ONLY_ADVISORY`

## Retrieval unit

`MemoryRetrievalUnit@v1` is the bounded ASKU analogue. ContextEnvelope receives these, never a memory dump.

Modes: CURRENT, HISTORICAL, WHAT_CHANGED, COUNTEREVIDENCE, OPERATOR_MEMORY, RESEARCH_EVIDENCE.

Office truth ≠ memory context. `overrides_office_truth=false`.

## Index

Do not canonicalize HNSW or IVFFlat.

Measured in this PR: synthetic exact cosine self-retrieval only.

Unmeasured: HNSW, IVFFlat, hybrid, Neo4j, production p95, LongMemEval-style numbers (`REFERENCE_TARGET_NOT_MEASURED`).

Recommendation: **INSUFFICIENT_DATA**.

## M2 isolated benchmark lanes (due diligence — no winner yet)

Do not apply `sql/r10_memory_shadow.sql` to production. Measure before choosing:

| lane | substrate |
|---|---|
| A | native Trade AI Postgres bitemporal shadow |
| B | native + pgvector |
| C | pgmnemo current stable shadow |

Metrics: bitemporal correctness, point-in-time queries, RLS, concurrency, retrieval quality, HNSW, IVFFlat, exact retrieval, hybrid retrieval, backup/restore, operational complexity.

Still forbidden as unmeasured mandates: Titan embeddings, HNSW-as-default, cosine self-ratified edges, 0.75 threshold, 10× over-fetch, SERIALIZABLE-everywhere, hardware isolation claims, private CoT persistence.

## ContextEnvelope M4 roadmap

TICKER_RESEARCH_STATE, LAST_CURATION, SEMANTIC_OPERATOR_MEMORY, PORTFOLIO_THESIS, RELEVANT_FEEDBACK, OUTCOMES, LESSONS, MEMORY_RETRIEVAL_UNITS.

`CIOContextEnvelope@v2` is nested in ContextEnvelope@v1 by the CIO consumption PR. Preserve `scripts/lib/agent_context_envelope.py` v1; do not silently override deterministic financial truth.
