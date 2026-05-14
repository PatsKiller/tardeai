# Phase 2C — Execution Scope

**Date:** 2026-05-14
**Phase:** 2C — Limited Hybrid Retrieval Pilot
**A1A Status:** ACTIVE

---

## Purpose

Phase 2B showed near-zero overlap (0.6% top-5) between nomic and qwen3 retrieval — they find materially different evidence. Phase 2C tests whether combining both into a hybrid retrieval strategy improves evidence coverage for high-value workflows.

## Authorized

- Build pilot-only hybrid retrieval helper (`hybrid_rag_retrieval_pilot.py`)
- Query both production nomic and qwen3 test index
- Merge, dedupe, and rerank results
- Report quality comparison
- Simulate workflow context improvement
- Write Phase 2C reports

## Blocked

- Changing production RAG routing
- Making hybrid the default for any production caller
- Promoting qwen3-embedding:8b
- Phase 2D execution
- Altering cron, .env, broker/execution

## Invariants

| Setting | Value | Changed? |
|---------|-------|----------|
| Production embedding | nomic-embed-text | NO |
| Production RAG routing | Unchanged | NO |
| Production content_embeddings | ~14,792 rows | NO |
| qwen3 test table | 1,000 rows | READ ONLY |
| Phase 1 cron | Unchanged | NO |
| ALPACA_MODE | paper | NO |
| LLM_DISABLE_LIVE_EXECUTION | true | NO |

## Phase 2D Promotion
**BLOCKED** — requires separate operator command.
