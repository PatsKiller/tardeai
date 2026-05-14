# Phase 2 — RAG Embedding A/B Testing

**Status:** Phase 2C NIGHTLY ENABLED. Daily 23:00 deep queue uses two-stage hybrid RAG. Friday extended disabled. Phase 2D blocked.
**Last commit:** (Phase 2C nightly enable, 2026-05-14)
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

## Phase 2B Results (Initial — 1,000 docs)

- 1,000 docs indexed with qwen3-embedding:8b in parallel table
- 40-query comparison: HYBRID_RECOMMENDED
- Top-5 overlap: 0.6% — models find completely different docs
- Source diversity: qwen3 2.1 types vs nomic 1.4 types (50% better)
- Latency: qwen3 321ms vs nomic 28ms (11x slower)
- See `v4_1_phase2b_evaluation_report.md` for full analysis

## Phase 2B-Expanded Results (4,897 docs — 2026-05-14)

- Expanded from 1,000 → 4,897 docs across 13 source types
- 3,897 new embeddings, 0 failures, 267ms avg latency, 18 min runtime
- **Verdict upgraded: QWEN3_BETTER**
- Qwen3 similarity: 0.647 vs nomic 0.612 (+6.2%)
- Source diversity: 3.0 vs nomic 1.4 (+114%)
- Consensus still very low (0.5%) — models find genuinely different documents
- Hybrid source diversity: 2.73 types/query (up from 1.88)
- Hybrid latency: 6.9s (acceptable for offline only)
- See `v4_1_phase2b2_expand_5000_evaluation_report.md` for full analysis

## Phase 2C Results (Initial — with 1,000 docs)

- Hybrid pilot ran 40 queries merging nomic (14,792 docs) + qwen3 (1,000 docs)
- Verdict: HYBRID_MARGINAL — qwen3 finds 56.5% unique items but consensus only 2.5%
- Source diversity: 1.88 types/query (vs nomic 1.4, qwen3 2.1)
- Latency: hybrid total 1.7s
- See `v4_1_phase2c_evaluation_report.md` for full analysis

## Phase 2C Offline Integration Pilot Results (2026-05-14)

- 5/5 jobs succeeded, 0 failures, 4.8 min runtime
- Hybrid adapter created (scripts/hybrid_rag_context_adapter.py)
- Queue runner updated with --use-hybrid-rag opt-in flag
- All 5 jobs used nomic-only fallback (qwen3-embedding not loaded during daytime)
- RAG context added to jobs that previously had NO RAG (SQL-only)
- Source diversity 1-6 types per query (previously 0)
- Latency overhead: 0.3-2.3s per job (0.4-5.2% of total)
- See `v4_1_phase2c_offline_integration_pilot_report.md`

## Nightly Enablement (2026-05-14)

Daily 23:00 deep queue now runs with `--enable-hybrid-rag`.
Two-stage lifecycle: Stage A prefetches with qwen3-embedding + nomic, Stage B runs gemma with cached context.
Friday extended: no hybrid (unchanged).
See `v4_1_phase2c_nightly_enable_scope.md`.

## Next Steps (Operator Decision Required)

> Observe tonight's first scheduled hybrid run.
> If clean: enable Friday extended hybrid.
> Phase 2D production promotion remains BLOCKED.

## Phase 2 Gates

| # | Gate | Status |
|---|------|--------|
| 1 | Candidate model installed | DONE |
| 2 | Baseline established (nomic) | DONE |
| 3 | Candidate A/B run | DONE |
| 4 | Parallel index built (1K) | DONE |
| 4b | Parallel index expanded (5K) | DONE (4,897 docs) |
| 5 | Retrieval comparison | DONE (QWEN3_BETTER) |
| 6 | Latency delta measured | DONE (274ms vs 28ms) |
| 7 | Offline integration pilot | DONE (20/20 jobs, two-stage) |
| 7b | Nightly enablement | DONE (daily 23:00 --enable-hybrid-rag) |
| 7c | Friday extended hybrid | PENDING operator approval |
| 8-14 | (See promotion checklist) | BLOCKED |

## Safety Invariants

These remain unchanged throughout Phase 2:
- `ALPACA_MODE=paper`
- `LLM_DISABLE_LIVE_EXECUTION=true`
- Phase 1H cron: UNCHANGED
- Production RAG routing: UNCHANGED
- Production embedding: nomic-embed-text
