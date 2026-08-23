# Hybrid Evidence Refresh and Hermes Bridge

Date: 2026-08-23  
Authority: `READ_ONLY_ADVISORY`  
Status: implemented in dry/read-only mode; not deployed and not authorized to publish theses.

## Problem

Hermes research is stored in `hermes_research_intelligence`, while the symbol
thesis gate reads curated RAG and approved structured sources. A Hermes brief
therefore could exist without being admissible evidence for a symbol thesis.
Freshness could mark a symbol stale, but no deterministic refresh request joined
Hermes discovery to independent primary/structured sources.

## Implemented bridge

`scripts/lib/hybrid_evidence.py` now provides:

- freshness-bounded Hermes normalization (`promoted` status, source URL, symbol,
  polarity, and seven-day freshness window)
- provenance including source family and independence group
- stable `HybridEvidenceRefreshRequest@v1` identifiers
- non-authoritative, non-enqueuing refresh requests

`symbol_thesis_evidence.py` now reads promoted Hermes rows when available and
maps bullish/bearish rows into supporting/contradictory evidence. Hermes does
not satisfy the independent primary-source requirement. Duplicate source IDs
are removed before sufficiency evaluation.

## Safety behavior

- staged, rejected, URL-less, malformed, or stale Hermes rows are ignored
- Hermes alone cannot satisfy the primary/approved-source floor
- missing evidence yields a refresh request with `enqueue=false`
- no LLM/provider call, thesis write, notification, or broker path is invoked
- current financial truth remains outside memory/research evidence

## Dry validation

```text
SCHD: BLOCKED_PENDING_ACQUISITION_AND_CURATION
SCHG: BLOCKED_PENDING_ACQUISITION_AND_CURATION
llm_calls_used: 0
```

The block is expected until promoted Hermes evidence and independent approved
sources are present in the live catalog. Unit coverage is in
`tests/test_hybrid_evidence.py`.

## Production follow-up gates

1. Add a read-only scheduler/outbox consumer for `HybridEvidenceRefreshRequest`.
2. Curate and embed official Schwab/SEC/structured sources plus Hermes evidence.
3. Re-run SCHD/SCHG dry validation and verify support/counter/primary counts.
4. Observe one natural refresh and identical-evidence replay.
5. Only then consider a separately authorized bounded synthesis call.
