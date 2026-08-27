# Phase 2C — Evaluation Report

**Date:** 2026-05-14
**Verdict:** HYBRID_MARGINAL — promising but limited by qwen3 index size

---

## 1. Executive Summary

Phase 2C tested a hybrid retrieval strategy combining production nomic-embed-text (14,792 docs) with qwen3-embedding:8b (1,000 docs). The models retrieve substantially different documents — qwen3 finds 56.5% unique items that nomic misses. However, consensus overlap is only 2.5%, limited by the qwen3 index size mismatch (1,000 vs 14,792 rows). Recommendation: expand qwen3 index to 5,000+ docs before pursuing offline integration.

## 2. Phase 2B Recap

- Near-zero retrieval overlap (0.6% top-5)
- qwen3 has 50% better source diversity
- Similar relevance scores
- 13x slower latency
- Verdict was HYBRID_RECOMMENDED

## 3. What Was Tested

- Built `hybrid_rag_retrieval_pilot.py` — queries both indexes, merges, dedupes, reranks
- Ran 40 queries across 20 categories
- Weighted reranking: similarity (0.50) + recency (0.15) + source boost (0.10) + diversity (0.10) + consensus (0.10) + base (0.05)
- Dedupe by source_type + source_id

## 4. What Was NOT Changed

- Production RAG routing: UNCHANGED
- Production content_embeddings: 14,792 rows (UNCHANGED)
- Cron: UNCHANGED
- .env: UNCHANGED
- Broker/execution: UNCHANGED
- Models restored: qwen3:14b + nomic-embed-text

## 5. Results

| Metric | Value |
|--------|-------|
| Queries | 40 |
| Empty results | 0/40 (0%) |
| Avg hybrid score | 0.699 |
| Avg source diversity | 1.88 types/query |
| Consensus (both models) | 10 items (2.5%) |
| Nomic-only | 164 items (41%) |
| Qwen3-only | 226 items (56.5%) |

### Latency

| Component | Avg |
|-----------|-----|
| Nomic embedding | 20ms |
| Qwen3 embedding | 314ms |
| Hybrid total | 1,713ms |

## 6. Analysis

### Why consensus is low
The qwen3 test table has only 1,000 rows while nomic has 14,792. For any given query, most nomic results come from the ~13,792 docs that don't exist in the qwen3 index at all. True overlap can only be measured with a full parallel index.

### Where qwen3 adds value
Qwen3 surfaces different documents than nomic for the same queries — 56.5% of hybrid results are unique to qwen3. This suggests the 4096-dim space captures different semantic relationships than nomic's 768-dim space.

### Source diversity improvement
Hybrid: 1.88 types/query vs nomic-only: 1.4 (34% improvement). The merged retrieval naturally pulls from more varied content categories.

### Noise concern
With low consensus, it's hard to judge whether qwen3's unique finds are genuinely better or just different-but-irrelevant. A larger index would help distinguish signal from noise.

## 7. Workflow Recommendations

| Workflow | Hybrid? | Reason |
|----------|---------|--------|
| Deep overnight queue | HOLD | Need larger index |
| Risk synthesis | HOLD | Need larger index |
| Recovery watch | HOLD | Need larger index |
| Journal review | HOLD | Need larger index |
| Proposal review | HOLD | Need larger index |
| Strategy classification | NO | nomic sufficient |
| Real-time agent context | NO | Latency too high (1.7s) |
| Market-hours queries | NO | Latency too high |

## 8. Phase 2C Status

**CONTINUE PILOT** — but expand qwen3 index first.

The hybrid architecture works mechanically (0 errors, clean merge/rerank, models restore properly). The limiting factor is qwen3 index coverage, not the hybrid approach itself.

## 9. Phase 2D Promotion

**BLOCKED** — requires:
1. Larger qwen3 index (5,000+ docs minimum)
2. Re-run hybrid comparison with matched coverage
3. Demonstrated quality improvement in offline workflows
4. 48-hour observation period
5. Explicit operator approval

## 10. Production Impact

- Production embeddings changed: **NO**
- Production RAG routing changed: **NO**
- Production content_embeddings: 14,792 (unchanged)
- Cron changed: **NO**
- .env changed: **NO**
- Broker/holdings/execution changed: **NO**
