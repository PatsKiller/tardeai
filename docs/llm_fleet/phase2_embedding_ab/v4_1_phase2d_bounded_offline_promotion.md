# Phase 2D — Bounded Offline Hybrid RAG Promotion

**Date:** 2026-05-14
**Status:** APPROVED (bounded offline only)

## Definition

Phase 2D is **NOT** global production embedding promotion.

Phase 2D in this system means: approve hybrid RAG for production use inside controlled deep/offline queues only, using the two-stage wrapper lifecycle.

## Approved

- Hybrid RAG for daily 23:00 deep overnight queue
- Hybrid RAG for Friday extended deep queue
- Two-stage lifecycle (Stage A prefetch → Stage B gemma generation)
- qwen3-embedding:8b as parallel hybrid retrieval source during Stage A only
- nomic-embed-text as baseline retrieval source
- gemma3-overnight for deep reasoning during Stage B only
- qwen3-embedding must unload before gemma loads
- Hybrid metrics logged per job
- Rollback helpers available

## Approved Job Types

risk_synthesis, recovery_watch_review, closed_trade_review, auto_journal_review,
manual_journal_review, journal_pattern_review, proposal_review,
strategy_classification (inside deep queue only)

## NOT Approved

- Global/default production RAG routing
- Market-hours hybrid RAG
- Real-time Telegram/OpenClaw hybrid RAG
- Broker/execution/risk-gate hybrid RAG
- Replacing nomic-embed-text as production embedding
- Deleting or migrating production content_embeddings
- Full production RAG re-index
- qwen3-embedding:8b as global default embedding model

## Explicit Statement

Phase 2D is approved only as bounded offline/deep-queue hybrid RAG production use.
Global production embedding promotion remains blocked.
