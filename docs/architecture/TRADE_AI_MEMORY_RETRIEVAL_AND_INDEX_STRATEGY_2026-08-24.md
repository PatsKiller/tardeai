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

## ContextEnvelope M4 roadmap (not this PR)

TICKER_RESEARCH_STATE, LAST_CURATION, SEMANTIC_OPERATOR_MEMORY, PORTFOLIO_THESIS, RELEVANT_FEEDBACK, OUTCOMES, LESSONS, MEMORY_RETRIEVAL_UNITS.

Preserve `scripts/lib/agent_context_envelope.py` v1; do not silently override deterministic financial truth.
