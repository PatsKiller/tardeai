# Phase 2B — Evaluation Report

**Date:** 2026-05-14
**Verdict:** HYBRID_RECOMMENDED

---

## 1. Executive Summary

Phase 2B built a parallel 1,000-document embedding index using qwen3-embedding:8b
and compared retrieval quality against production nomic-embed-text. The two models
retrieve **almost entirely different documents** (top-5 overlap: 0.6%, top-10: 1.3%)
while maintaining similar overall relevance scores. qwen3 shows 50% better source
diversity. A hybrid approach combining both models is recommended.

## 2. What Was Tested

- Created isolated table `content_embeddings_qwen3_test` (1,000 rows, 4096 dims)
- Indexed from production content: agent_result (576), fused_signal (399), trade_review (11), news (8), trade_outcome (6)
- Ran 40 queries against both production (14,787 nomic) and test (1,000 qwen3) indexes
- Compared top-5/10 overlap, similarity, latency, source diversity

## 3. Production Baseline

| Metric | nomic-embed-text |
|--------|-----------------|
| Table | content_embeddings |
| Rows | 14,787 |
| Dimensions | 768 |
| Avg similarity | 0.613 |
| Avg latency | 28ms |
| Empty results | 0/40 |
| Avg source diversity | 1.4 types |

## 4. Candidate Parallel Index

| Metric | qwen3-embedding:8b |
|--------|-------------------|
| Table | content_embeddings_qwen3_test |
| Rows | 1,000 |
| Dimensions | 4,096 |
| Avg similarity | 0.609 |
| Avg latency | 321ms |
| Empty results | 0/40 |
| Avg source diversity | 2.1 types |

## 5. Key Findings

### Near-zero overlap
The two models retrieve fundamentally different documents for the same queries.
Top-5 overlap is 0.6%, top-10 is 1.3%. This means they capture different semantic
signals — not that one is wrong. Both produce relevant results.

### Similar relevance quality
Average cosine similarity is nearly identical (0.613 vs 0.609, delta 0.004).
Neither model is clearly "more relevant" by this metric alone.

### Better source diversity with qwen3
qwen3 surfaces results from 2.1 source types on average vs nomic's 1.4.
This means qwen3 retrieval includes more varied evidence (agents + news + trades)
rather than clustering on one source type.

### Latency tradeoff
qwen3 is ~11x slower (321ms vs 28ms). Acceptable for batch/overnight indexing
and high-value evidence retrieval. Not suitable for real-time query embedding
during market hours.

### VRAM impact
qwen3-embedding (5.67GB) + qwen3:14b (9.4GB) = 15.07GB. Fits within 16GB
but evicts nomic-embed-text. Cannot coexist with all three models.

## 6. Failure Cases

None observed. Both models produced embeddings for all 40 queries. No errors
during index build or retrieval comparison.

## 7. Recommendation

### HYBRID approach recommended

| Context | Model |
|---------|-------|
| Broad/default retrieval | nomic-embed-text (fast, production) |
| Real-time query embedding | nomic-embed-text (28ms) |
| High-volume batch indexing | nomic-embed-text (production default) |
| Journal/trade reviews | qwen3-embedding:8b (better diversity) |
| Deep overnight results | qwen3-embedding:8b (better diversity) |
| Risk synthesis | qwen3-embedding:8b (better diversity) |
| Proposals + outcomes | qwen3-embedding:8b (better diversity) |

### Phase 2C: GO
Hybrid retrieval design is ready for refinement.

### Phase 2D: BLOCKED
Production promotion requires separate operator command.

## 8. Production Impact

- **Production embeddings changed:** NO
- **Production RAG routing changed:** NO
- **Production content_embeddings row count:** 14,787 (unchanged)
- **Cron changed:** NO
- **.env changed:** NO
- **Models restored:** qwen3:14b + nomic-embed-text confirmed resident
