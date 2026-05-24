# Phase 2G — Limited Hybrid RAG Canary

**Date:** 2026-05-14
**Status:** COMPLETE

## Purpose

Bounded canary of hybrid RAG for approved offline/read-only workflows based on Phase 2F evidence.

## Phase 2F Evidence

- Nomic avg similarity: 0.688, Qwen3: 0.634, **Hybrid: 0.699** (best)
- Qwen3 diversity: 2.7 (best), Nomic: 2.4
- Models complementary: 97% unique results, 2.9% consensus
- Nomic 14x faster (93ms vs 1,285ms)

## Canary Configuration

Config: `config/phase2g_hybrid_canary.yaml`

## Allowed Workflows

risk_synthesis, recovery_watch_review, closed_trade_review, auto_journal_review,
manual_journal_review, journal_pattern_review, proposal_review, rag_content_curation,
post_market_report_context, weekly_summary_context, offline_dashboard_context,
strategy_classification_deep_only

## Blocked Workflows

market_hours_watchlist_agent, telegram_realtime, openclaw_interactive, broker_execution,
risk_gate, paper_trade_monitor, order_placement, active_stop_target_execution,
global_rag_api_default

## Canary Result

- 16/16 queries OK, 0 errors
- 6 workflows tested
- Source diversity: 2.4 types/query
- Blocked workflow test: correctly refused

## Production Unchanged

nomic-embed-text remains global production default. Phase 2H blocked.
