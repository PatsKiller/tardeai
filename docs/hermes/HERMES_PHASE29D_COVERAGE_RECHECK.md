# Hermes Phase 29D — Coverage Recheck After Safe Views

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Updated Coverage Matrix

| # | Surface | Phase 28 Status | Phase 29 Status | View |
|---|---------|----------------|-----------------|------|
| 1 | Trade journal | NOT COVERED | **COVERED** | hermes_v_journal_learning_context (0 rows, ready) |
| 2 | Journal learning | NOT COVERED | **COVERED** | hermes_v_journal_learning_context |
| 3 | Closed trade case studies | PARTIALLY COVERED | PARTIALLY COVERED | hermes_v_trade_reflection_context (existing) |
| 4 | Backtesting results | NOT COVERED | **COVERED** | hermes_v_backtest_results_context (40 rows) |
| 5 | Rejected/expired proposal replay | PARTIALLY COVERED | PARTIALLY COVERED | hermes_v_proposal_context (existing) |
| 6 | Momentum scout | NOT COVERED | **COVERED** | hermes_v_screener_context (211 rows) |
| 7 | Morning briefs | NOT COVERED | **NOT COVERED** | File-only, no DB table |
| 8 | Catalyst/news enrichment | PARTIALLY COVERED | **COVERED** | hermes_v_catalyst_quality_context (345 rows) + existing news view |
| 9 | Analyst/external sources | COVERED | COVERED | via news + agent views + SearXNG source_discovery |
| 10 | Telegram/AI analyst | PARTIAL | PARTIAL | Metadata only (30-day retention) |

## Summary

| Status | Phase 28 | Phase 29 |
|--------|----------|----------|
| COVERED | 1 | **6** |
| PARTIALLY COVERED | 3 | 3 |
| NOT COVERED | 6 | **1** (morning briefs) |

**Hermes now analyzing: 9 of 10 surfaces (up from 4)**

## Remaining Gap

| Surface | Issue | Resolution Path |
|---------|-------|----------------|
| Morning briefs | File-only storage, no DB table | Phase 29E design (below) |

## View Inventory: 12 Total

| View | Rows | Source |
|------|------|--------|
| hermes_v_ticker_context | 33K+ | ticker snapshots |
| hermes_v_proposal_context | 145 | proposals |
| hermes_v_trade_reflection_context | 157 | closed trades |
| hermes_v_news_research_context | 4.9K | news articles |
| hermes_v_agent_results_context | 9K | agent outputs |
| hermes_v_pipeline_health_context | 2.9K | pipeline runs |
| hermes_v_rag_context_metadata | 25K | embeddings |
| hermes_v_portfolio_context | 13 | portfolio summary |
| hermes_v_journal_learning_context | 0 | thesis reviews |
| hermes_v_backtest_results_context | 40 | backtest results |
| hermes_v_screener_context | 211 | screener health |
| hermes_v_catalyst_quality_context | 345 | catalyst events |
