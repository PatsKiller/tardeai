# Phase 2B Expanded — 5,000 Document Evaluation Report

**Date:** 2026-05-14
**Phase:** 2B-Expanded
**Status:** COMPLETE

## Executive Summary

Expanded the qwen3-embedding:8b parallel test index from 1,000 to 4,897 documents across 13 source types. The expansion resolved the source coverage gap (5 → 13 types) and produced stronger parallel retrieval metrics. Qwen3 now outperforms nomic on average similarity (0.6465 vs 0.6121) and source diversity (3.0 vs 1.4 types/query). Consensus between models remains very low (0.5%), confirming the two models genuinely find different relevant documents. Hybrid retrieval provides significant source diversity benefit (2.73 types/query) but carries a latency cost (~6.9s total) that limits it to offline/batch use cases.

## Starting State

| Metric | Value |
|--------|-------|
| Production embeddings (nomic) | 14,796 |
| Qwen3 test embeddings | 1,000 |
| Source types in qwen3 | 5 of 14 |
| Phase 2C consensus | 2.5% |
| Phase 2C verdict | HOLD — need larger index |

## Ending State

| Metric | Value |
|--------|-------|
| Production embeddings (nomic) | 14,798 (unchanged by this work) |
| Qwen3 test embeddings | 4,897 |
| Rows added | 3,897 |
| Source types in qwen3 | 13 of 14 |
| Build runtime | 1,066s (~18 min) |
| Avg embedding latency | 267.9ms |
| Failed embeddings | 0 |
| Skipped (no title) | 0 |

### Source Mix After Expansion

| Source | Count | % |
|--------|-------|---|
| agent_result | 1,500 | 30.6% |
| fused_signal | 900 | 18.4% |
| news | 600 | 12.2% |
| decision_outcome | 500 | 10.2% |
| cio_decision | 400 | 8.2% |
| agent_synthesis | 400 | 8.2% |
| youtube | 250 | 5.1% |
| social_post | 200 | 4.1% |
| sec_form4 | 100 | 2.0% |
| fred_series | 28 | 0.6% |
| trade_review | 11 | 0.2% |
| trade_outcome | 7 | 0.1% |
| brave_cache | 1 | <0.1% |

## Parallel Retrieval Comparison (Old vs New)

| Metric | 1K Index | 5K Index | Change |
|--------|----------|----------|--------|
| Avg top-5 overlap | 0.006 | 0.003 | Similar (near zero) |
| Avg top-10 overlap | 0.013 | 0.003 | Similar (near zero) |
| Nomic avg similarity | 0.613 | 0.612 | Stable |
| Qwen3 avg similarity | 0.609 | 0.647 | **+6.2% improvement** |
| Nomic avg latency | 28ms | 28ms | Same |
| Qwen3 avg latency | 321ms | 274ms | **15% faster** |
| Nomic source diversity | 1.43 | 1.4 | Same |
| Qwen3 source diversity | 2.08 | 3.0 | **+44% improvement** |
| Empty results | 0/40 | 0/40 | Same |
| Verdict | HYBRID_RECOMMENDED | **QWEN3_BETTER** | Upgraded |

**Key finding:** With 5x more documents and full source coverage, qwen3 now produces higher-quality retrieval results than nomic on average similarity (0.647 vs 0.612) and significantly better source diversity (3.0 vs 1.4). The verdict upgraded from HYBRID_RECOMMENDED to QWEN3_BETTER.

## Hybrid Retrieval Comparison (Old vs New)

| Metric | 1K Index | 5K Index | Change |
|--------|----------|----------|--------|
| Hybrid source diversity | 1.88 | 2.73 | **+45% improvement** |
| Hybrid avg score | N/A | 0.704 | New metric |
| Consensus items | 10 (2.5%) | 2 (0.5%) | Decreased |
| Nomic-only items | 164 (41%) | 112 (28%) | Decreased |
| Qwen3-only items | 226 (56.5%) | 286 (71.5%) | Increased |
| Hybrid latency | 1,713ms | 6,881ms | Increased |
| Empty results | 0% | 0% | Same |
| Verdict | HYBRID_MARGINAL | HYBRID_MARGINAL | Same |

## Analysis

### Did 5,000 docs fix the coverage issue?
**Partially.** Source type coverage went from 5 → 13 types. Source diversity improved dramatically (3.0 vs 2.08). However, consensus between models did not increase — it decreased from 2.5% to 0.5%. This is not a coverage artifact; the models genuinely embed and rank documents differently.

### Is 5,000 docs enough?
**For source diversity: yes.** 13 of 14 source types are covered. For consensus measurement: the low consensus is structural, not coverage-related. Expanding to 10,000 is unlikely to change this pattern.

### Why is consensus so low?
qwen3-embedding:8b (4096d) and nomic-embed-text (768d) have fundamentally different embedding spaces. They surface different relevant documents for the same query. This is actually the core value proposition for hybrid — the models complement each other rather than duplicating results.

### Is qwen3 finding useful documents?
**Yes.** qwen3 avg similarity improved from 0.609 → 0.647 with more data, and its source diversity of 3.0 types/query means it pulls from varied sources. The qwen3-only items (286/400 = 71.5%) represent documents that nomic would miss entirely.

### Latency concern
Hybrid latency increased from 1.7s to 6.9s. This is driven by the reranker processing more documents. This is acceptable for offline batch jobs (deep overnight, journal review) but too slow for real-time queries.

## Recommendation

**Recommend: Phase 2C offline integration pilot for deep overnight jobs only.**

Rationale:
1. qwen3 demonstrates clear quality advantage (0.647 vs 0.612 similarity)
2. Source diversity benefit is significant (3.0 vs 1.4)
3. Low consensus confirms models are complementary, not redundant
4. Hybrid latency (~7s) is acceptable for offline jobs, not for real-time
5. Full source type coverage achieved
6. Zero failures, clean model lifecycle management

Phase 2C offline pilot should:
- Wire hybrid retrieval into deep overnight agent context only
- Keep nomic-only for all real-time queries
- Monitor for 48 hours
- Compare deep overnight output quality with and without hybrid context
- Require operator approval before expanding to real-time

Do NOT:
- Promote qwen3 to production
- Replace nomic-embed-text
- Change production RAG routing for real-time queries
- Change cron, .env, broker, or execution behavior

## Production Unchanged Statement

| Item | Changed? |
|------|----------|
| Production content_embeddings | **NO** |
| Production RAG routing | **NO** |
| Cron schedule | **NO** |
| .env | **NO** |
| Broker/holdings/execution | **NO** |
| Phase 2D promotion | **BLOCKED** — requires explicit operator approval |

## Final Model Residency

| Model | Status |
|-------|--------|
| nomic-embed-text | Resident (production) |
| qwen3:14b | Resident (production inference) |
| qwen3-embedding:8b | Unloaded (test only) |
