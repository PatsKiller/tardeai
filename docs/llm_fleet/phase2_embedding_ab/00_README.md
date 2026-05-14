# Phase 2 — RAG Embedding A/B Testing

**Status:** Phase 2B COMPLETE. HYBRID_RECOMMENDED. Phase 2C pending operator approval.
**Last commit:** (Phase 2B)
**Owner:** John W. Whiting

## What This Is

Phase 2 of the LLM Fleet v4.1 plan evaluates whether to replace
`nomic-embed-text` (current production embedding) with
`qwen3-embedding:8b` for improved retrieval quality across RAG.

## Current State

- **Production embedding:** `nomic-embed-text` (UNCHANGED)
- **Candidate:** `qwen3-embedding:8b` (INSTALLED, 4.7 GB, 4096 dims)
- **Baseline:** nomic 768d, 23ms avg, 0/40 empty
- **Candidate test:** 4096d, 295ms avg, 0/40 empty
- **Production routing:** UNCHANGED
- **Cron:** UNCHANGED
- **Promotion status:** BLOCKED pending operator approval

## Read Order

1. `v4_1_phase2_a1a_scope.md` — what this initiative covers
2. `v4_1_phase2_preflight.md` — preflight checks performed
3. `v4_1_phase2_rag_embedding_discovery.md` — production embedding architecture
4. `v4_1_phase2_candidate_model_check.md` — qwen3-embedding:8b status
5. `v4_1_phase2_embedding_ab_queries.md` — 40 test queries across 20 categories
6. `v4_1_phase2_embedding_ab_report.md` — A/B results
7. `v4_1_phase2_embedding_ab_results.json` — raw JSON
8. `v4_1_phase2b_parallel_index_design.md` — design only, pending approval
9. `v4_1_phase2c_hybrid_retrieval_design.md` — design only, pending approval
10. `v4_1_phase2d_embedding_promotion_checklist.md` — 14 gates, blocked

## Phase 2B Results

- 1,000 docs indexed with qwen3-embedding:8b in parallel table
- 40-query comparison: HYBRID_RECOMMENDED
- Top-5 overlap: 0.6% — models find completely different docs
- Source diversity: qwen3 2.1 types vs nomic 1.4 types (50% better)
- Latency: qwen3 321ms vs nomic 28ms (11x slower)
- See `v4_1_phase2b_evaluation_report.md` for full analysis

## Next Steps (Operator Decision Required)

> Begin Phase 2C limited hybrid retrieval pilot.

## Phase 2 Gates

| # | Gate | Status |
|---|------|--------|
| 1 | Candidate model installed | DONE |
| 2 | Baseline established (nomic) | DONE |
| 3 | Candidate A/B run | DONE |
| 4 | Parallel index built | DONE (1,000 docs) |
| 5 | Retrieval comparison | DONE (HYBRID_RECOMMENDED) |
| 6 | Latency delta measured | DONE (321ms vs 28ms) |
| 7-14 | (See promotion checklist) | BLOCKED |

## Safety Invariants

These remain unchanged throughout Phase 2:
- `ALPACA_MODE=paper`
- `LLM_DISABLE_LIVE_EXECUTION=true`
- Phase 1H cron: UNCHANGED
- Production RAG routing: UNCHANGED
- Production embedding: nomic-embed-text
