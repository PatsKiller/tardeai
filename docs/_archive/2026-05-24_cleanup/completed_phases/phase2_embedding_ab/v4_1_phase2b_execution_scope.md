# Phase 2B — Execution Scope

**Date:** 2026-05-14
**Phase:** 2B — Limited Parallel Embedding Index Test
**A1A Status:** ACTIVE

---

## Authorized

- Create isolated parallel embedding table `content_embeddings_qwen3_test`
- Populate with up to 1,000 docs using qwen3-embedding:8b
- Compare retrieval quality against production nomic-embed-text
- Write Phase 2B reports under `docs/llm_fleet/phase2_embedding_ab/`
- Update project documentation index per A1A

## Blocked

- Production embedding promotion (requires Phase 2D + operator command)
- Production RAG routing changes
- Full production re-index
- Phase 2C hybrid routing implementation
- Phase 1 cron changes
- Deep overnight queue changes
- .env modifications
- Broker/holdings/execution changes

## Invariants

| Setting | Value | Changed? |
|---------|-------|----------|
| Production embedding | nomic-embed-text | NO |
| Production RAG routing | Unchanged | NO |
| Production content_embeddings | 14,787 rows, untouched | NO |
| Phase 1 cron | Daily 23:00 + Friday 16:00 | NO |
| ALPACA_MODE | paper | NO |
| LLM_DISABLE_LIVE_EXECUTION | true | NO |
| qwen3:14b | Default STANDARD/REALTIME | NO |

## Phase 2D Promotion

**BLOCKED** — requires separate operator command:
> Begin Phase 2D production embedding promotion.
