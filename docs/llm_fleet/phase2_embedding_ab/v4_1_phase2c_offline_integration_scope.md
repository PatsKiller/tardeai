# Phase 2C Offline Integration Pilot — Scope

**Date:** 2026-05-14
**Phase:** 2C Offline Integration
**Status:** PILOT COMPLETE (5 jobs)

## Why Phase 2C Offline Integration Is Approved

Phase 2B-expanded demonstrated:
- qwen3 similarity 0.647 vs nomic 0.612 (+6.2%)
- Source diversity 3.0 vs 1.4 (+114%)
- Models are complementary (0.5% consensus — they find different relevant docs)
- 4,897 qwen3 test docs across 13 source types
- Zero failures, clean model lifecycle

Hybrid RAG adds broader evidence coverage for deep overnight jobs where latency
is acceptable (~2-7s per query) and the goal is comprehensive analysis.

## Production/Global RAG Routing

**UNCHANGED.** All real-time and market-hours RAG queries use nomic-embed-text only.

## Allowed Job Types (Pilot)

- risk_synthesis
- recovery_watch_review
- closed_trade_review
- auto_journal_review
- manual_journal_review
- journal_pattern_review
- proposal_review
- strategy_classification (deep overnight queue only)

## Blocked Job Types

- Market-hours process_watchlist_agent_jobs.py
- Telegram real-time agent replies
- OpenClaw interactive responses
- Broker/execution/risk gate decisions
- Paper trade monitor
- Live/paper order placement
- Active stop/target execution

## Latency Rationale

Hybrid RAG adds ~2-7s per query. For deep overnight batch jobs running during
the 8 PM–3 AM window, this is negligible compared to gemma3 inference (~50-65s/job).

## Safety and Rollback

- Hybrid RAG is opt-in only (--use-hybrid-rag flag)
- Falls back to nomic-only if qwen3-embedding unavailable
- No writes to production embeddings
- No changes to cron
- Remove --use-hybrid-rag flag to instantly revert
- Phase 2D promotion remains BLOCKED
