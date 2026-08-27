# Phase 2 — Final Closeout Report

**Date:** 2026-05-14 (updated: Phase 2H bounded approval)
**Status:** COMPLETE — all phases through Phase 2H
**Global embedding promotion:** BLOCKED

## Summary

Phase 2 evaluated whether qwen3-embedding:8b could improve RAG retrieval quality.
Result: qwen3 outperforms nomic on similarity and source diversity, but is 10x slower.
The models are complementary (0.5% consensus — they find different relevant documents).
Hybrid retrieval is approved for offline deep overnight jobs only.

## Phase 2A — Candidate Evaluation

- qwen3-embedding:8b installed (4.7 GB, 4096 dims)
- nomic-embed-text baseline established (274 MB, 768 dims, 23ms)
- 40-query A/B comparison: both models functional, different retrieval patterns
- Production unchanged

## Phase 2B — Parallel Index

- content_embeddings_qwen3_test table created
- Initial 1,000-doc test: 5 of 14 source types covered
- Expanded to 4,897 docs across 13 source types
- qwen3 similarity: 0.647 vs nomic 0.612 (+6.2%)
- qwen3 source diversity: 3.0 vs nomic 1.4 (+114%)
- Verdict upgraded from HYBRID_RECOMMENDED to QWEN3_BETTER
- Production unchanged

## Phase 2C — Hybrid Integration

- Hybrid retrieval pilot: 40-query test, 20-job two-stage pilot
- Two-stage lifecycle: Stage A (embed prefetch) → Stage B (gemma generation)
- Hard rule: qwen3-embedding and gemma3-overnight never co-resident
- Deep overnight jobs gained RAG context (previously had none — SQL-only)
- Daily 23:00 hybrid enabled
- Friday extended hybrid enabled
- Monitor + rollback helpers deployed

## Phase 2D — Bounded Offline Promotion

- Hybrid RAG approved for daily + Friday deep queues
- Global production RAG routing unchanged
- nomic-embed-text remains production embedding
- qwen3-embedding:8b is parallel offline retrieval only
- Global embedding promotion explicitly blocked

## Current Production Model State

| Role | Model | Status |
|------|-------|--------|
| Standard inference | qwen3:14b | Resident (production) |
| Production embedding | nomic-embed-text | Resident (production) |
| Hybrid offline retrieval | qwen3-embedding:8b | Loaded only during Stage A prefetch |
| Deep reasoning | gemma3-overnight | Loaded only during Stage B |

## Current Cron

**Daily:** `0 23 * * * ... --enable-hybrid-rag >> logs/deep_overnight_llm_window.log`
**Friday:** `0 16 * * 5 ... --enable-hybrid-rag --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log`

## Rollback

- `./scripts/rollback_phase2c_hybrid_nightly.sh --daily` — rollback daily only
- `./scripts/rollback_phase2c_hybrid_nightly.sh --friday` — rollback Friday only
- `./scripts/rollback_phase2c_hybrid_nightly.sh --all` — rollback both

## Safety

- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings guard active
- No broker/execution changes throughout Phase 2

## Phase 2H: Bounded Offline Hybrid Approval

- Hybrid RAG formally approved for 14 offline/deep/read-only workflows
- 9 workflows explicitly blocked (market-hours, real-time, execution)
- Policy config: `config/phase2h_bounded_hybrid_rag_policy.yaml`
- Audit: `.venv/bin/python scripts/audit_phase2h_bounded_approval.py`
- All blocked enforcement tests: PASS
- Global production embedding promotion: BLOCKED

## Remaining Work (Not Phase 2)

- Phase 3: Small media/prose model pilot
- Phase 4: Dashboards/alerts enhancements
- Phase 5: Learning loop improvements

## Final Phase 2 Status

**COMPLETE** — all phases 2A through 2H.
**Phase 2H** approved bounded offline/deep hybrid RAG as production behavior.
**BLOCKED** — global production embedding promotion remains a separate future decision.

**Next recommended phase:** Phase 3 — Small media/prose model pilot.
