# Phase 2A — Embedding A/B Baseline Report

**Date:** 2026-05-14
**Status:** Both models tested, candidate shows promise

---

## Summary

| Metric | Baseline (nomic-embed-text) | Candidate (qwen3-embedding:8b) |
|--------|---------------------------|-------------------------------|
| Installed | YES | YES (pulled 2026-05-14) |
| Dimensions | 768 | 4,096 |
| Disk size | 274 MB | 4.7 GB |
| VRAM resident | 0.54 GB | 5.67 GB |
| Avg embedding latency | 23ms | 295ms |
| Empty results | 0/40 | 0/40 |
| Source diversity (top-5) | 5 types | N/A (no candidate index yet) |
| Docs sampled | 1,000 | N/A |
| Queries tested | 40 | 40 |

## VRAM Coexistence

- qwen3-embedding (5.67 GB) + qwen3:14b (9.4 GB) = **15.07 GB** — fits within 16 GB
- BUT nomic-embed-text (0.54 GB) gets evicted when qwen3-embedding loads
- qwen3-embedding CANNOT coexist with both qwen3:14b AND nomic-embed-text
- For production: qwen3-embedding would REPLACE nomic, not coexist

## Production Impact

- **No production embeddings changed:** TRUE
- **No production RAG routing changed:** TRUE
- **No cron changed:** TRUE
- **No .env changed:** TRUE
- **Production models restored:** qwen3:14b + nomic-embed-text confirmed resident after test

## Key Findings

### Latency
- nomic: 23ms — very fast, suitable for real-time
- qwen3-embedding: 295ms — ~13x slower, but acceptable for batch/overnight indexing
- For real-time queries during market hours, latency is a concern
- For overnight batch indexing, 295ms per doc is fine (1,000 docs ≈ 5 min)

### Dimensions
- nomic: 768 dims — standard, compact
- qwen3-embedding: 4,096 dims — 5.3x more dimensions
- Higher dimensions may capture more semantic nuance but increase storage
- Current JSON embedding storage: ~6KB per doc at 768d → ~32KB per doc at 4096d
- 14,784 docs × 32KB ≈ 460 MB (vs current ~90 MB)

### Quality
- Both models produced embeddings for all 40 queries (0 empty)
- **Retrieval quality comparison not possible yet** — candidate embeddings only exist for queries, not for documents in the database
- Phase 2B parallel index needed to compare retrieval quality

## Verdict

**INCONCLUSIVE** — Both models produce embeddings successfully. Candidate has 5.3x more dimensions (potentially better semantic quality) but 13x slower latency. Retrieval quality comparison requires Phase 2B parallel index.

## Phase 2B Recommendation

**GO** — Candidate is functional and fits within VRAM constraints. Recommend building a limited parallel test index (500-2,000 docs) to compare actual retrieval quality. Use separate table `content_embeddings_qwen3_test` per Phase 2B design.

## Phase 2D Promotion Status

**BLOCKED** — Production embedding promotion requires separate operator command:

> Begin Phase 2D production embedding promotion.

This cannot be issued until Phase 2B parallel index shows quality >= baseline.
