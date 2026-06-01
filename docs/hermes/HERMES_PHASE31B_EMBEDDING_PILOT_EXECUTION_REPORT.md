# Hermes Phase 31B — Embedding Pilot Execution Report

**Date:** 2026-06-01
**Status:** COMPLETE — 2 embeddings created

## Embedded Records

| Source ID | Symbol | content_embeddings ID | Model | Dims |
|-----------|--------|-----------------------|-------|------|
| 12 | SCHD | 27540 | nomic-embed-text | 768 |
| 13 | TRX | 27541 | nomic-embed-text | 768 |

## Before/After

| Metric | Before | After |
|--------|--------|-------|
| content_embeddings (hermes_research) | 7 | 9 |
| hermes_embedding_queue completed | 7 | 9 |

## Notes

- SCHD embedded on first attempt
- TRX timed out on worker (30s timeout), succeeded with direct 120s timeout
- Both 768-dim nomic-embed-text vectors

## Safety

- [x] Exactly 2 records embedded (at cap)
- [x] Only source_ids 12 and 13
- [x] source_type = hermes_research
- [x] No other records touched
- [x] No promotions
- [x] No proposal/trade/journal mutations
- [x] Rollback ready: HERMES_PHASE31_EMBEDDING_PILOT_ROLLBACK.sql
