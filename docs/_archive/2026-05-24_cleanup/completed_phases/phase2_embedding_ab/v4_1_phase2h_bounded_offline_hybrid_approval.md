# Phase 2H — Bounded Offline Hybrid RAG Approval

**Date:** 2026-05-14
**Status:** APPROVED (bounded offline only)

## Definition

Phase 2H approves hybrid RAG only for bounded offline/deep/read-only production workflows. It does not approve global production embedding promotion.

## What Is Approved

- Hybrid RAG for daily 23:00 deep overnight queue
- Hybrid RAG for Friday extended deep queue
- Hybrid RAG for 14 named offline/read-only workflows
- Two-stage lifecycle (qwen3-embedding prefetch → gemma generation)
- qwen3-embedding:8b as shadow/hybrid retrieval source
- nomic-embed-text as baseline retrieval source
- Policy-gated workflow enforcement

## What Is NOT Approved

- Global/default production RAG routing
- Replacing nomic-embed-text as production embedding
- Market-hours hybrid RAG
- Real-time Telegram/OpenClaw hybrid RAG
- Broker/execution/risk-gate hybrid RAG
- qwen3-embedding:8b as global default embedding
- Full production RAG re-index with qwen3

## Model State

| Role | Model | Status |
|------|-------|--------|
| Standard inference | qwen3:14b | Production resident |
| Production embedding | nomic-embed-text | Production resident, global default |
| Hybrid offline retrieval | qwen3-embedding:8b | Shadow/hybrid, loaded during Stage A only |
| Deep reasoning | gemma3-overnight | Loaded during Stage B only |

## Approved Workflows (14)

risk_synthesis, recovery_watch_review, closed_trade_review, auto_journal_review,
manual_journal_review, journal_pattern_review, proposal_review, rag_content_curation,
post_market_report_context, weekly_summary_context, offline_dashboard_context,
strategy_classification_deep_only, daily_deep_overnight_queue, friday_extended_deep_queue

## Blocked Workflows (9)

market_hours_watchlist_agent, telegram_realtime, openclaw_interactive, broker_execution,
risk_gate, paper_trade_monitor, order_placement, active_stop_target_execution,
global_rag_api_default

## Rollback

`./scripts/rollback_phase2g_canary.sh --disable`

## Explicit Statement

nomic-embed-text remains the production/default embedding model.

qwen3-embedding:8b remains a shadow/hybrid retrieval source.

Global production RAG promotion remains blocked pending a future, separate operator command.
