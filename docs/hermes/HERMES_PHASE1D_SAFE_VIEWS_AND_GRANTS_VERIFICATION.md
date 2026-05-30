# Hermes Phase 1D — Safe Views and Grants Verification

**Date:** 2026-05-30
**Status:** PASS — all checks verified

---

## 1. Views Found (8/8 expected)

| View | Owner | Base Tables | Rows |
|------|-------|-------------|------|
| hermes_v_ticker_context | trade_ai | ticker_snapshot_daily, intelligence_entities, fused_signals | 33,625 |
| hermes_v_proposal_context | trade_ai | paper_trade_proposals | 145 |
| hermes_v_trade_reflection_context | trade_ai | paper_trades, trade_closed | 157 |
| hermes_v_news_research_context | trade_ai | news_articles | 4,994 |
| hermes_v_agent_results_context | trade_ai | watchlist_agent_results | 9,006 |
| hermes_v_pipeline_health_context | trade_ai | pipeline_runs, pipeline_definitions | 2,973 |
| hermes_v_rag_context_metadata | trade_ai | content_embeddings | 25,979 |
| hermes_v_portfolio_context | trade_ai | stopped_out_watch | 13 |

**All 8 expected views present: YES**

---

## 2. Sensitive Column Exclusion

| View | Sensitive Column | Excluded? |
|------|-----------------|-----------|
| hermes_v_proposal_context | `proposed_account` (raw) | YES — masked to `account_type` (IRA/Roth/401k/Taxable) |
| hermes_v_proposal_context | `account` column | NOT present in view |
| hermes_v_trade_reflection_context | `account` (raw) | YES — masked to `account_type` |
| hermes_v_portfolio_context | `account` (raw) | YES — masked to `account_type` |
| hermes_v_news_research_context | `raw_payload` | YES — excluded |
| hermes_v_agent_results_context | `raw_response` | YES — excluded |
| hermes_v_agent_results_context | `input_data_snapshot` | YES — excluded |
| hermes_v_agent_results_context | `full_result` | YES — excluded |
| hermes_v_agent_results_context | `full_narrative` | YES — excluded |
| hermes_v_rag_context_metadata | `embedding` (768-dim vector) | YES — excluded |
| hermes_v_rag_context_metadata | `tfidf_terms` | YES — excluded |

**All sensitive columns excluded/masked: YES**

---

## 3. hermes_readonly Grants

### View grants (8 + 1 staging table)
- SELECT on all 8 hermes_v_* views
- SELECT on hermes_validation_findings (staging table — part of Phase 1A)

### Direct table grants (37 tables, SELECT only)
All 37 tables are from the Phase 1C ALLOW list (no sensitive columns):
- Market/ticker: ticker_snapshot_daily, fused_signals, market_quotes, indicator_confluence_cache, catalyst_events
- Strategy: trade_ai_scans, ticker_strategy_classifications, strategy_performance_snapshots, strategy_lesson_rollup, strategy_registry, finviz_screeners
- Intelligence: news_articles, intelligence_entities, content_entity_links, research_insights, deep_overnight_llm_results, llm_intelligence_cache, agent_intelligence_rules, social_posts, social_sentiment_history, youtube_transcripts, sec_form4, fred_economic_series
- Proposals/trades: paper_trade_multi_reviews, proposal_outcome_chain, proposal_event_log, paper_execution_quality
- Portfolio: portfolio_snapshots, portfolio_intelligence_events, recovery_outcome_log
- System: system_health_checks, system_health_events, alert_events, alert_effectiveness, notification_log, daily_system_metrics, confidence_calibration_history

### Non-SELECT grants
**ZERO** — hermes_readonly has SELECT only, no INSERT/UPDATE/DELETE anywhere.

### Total hermes_readonly grants: 46 (8 views + 1 staging + 37 direct tables)

---

## 4. Denied Tables Verification

Checked all 14 denied tables — **ZERO grants found**:

| Table | Grant to hermes_* | Status |
|-------|-------------------|--------|
| personal_situation | NONE | DENIED |
| personal_tax_history | NONE | DENIED |
| personal_history | NONE | DENIED |
| tax_events | NONE | DENIED |
| telegram_proposal_messages | NONE | DENIED |
| paper_trade_commands | NONE | DENIED |
| accounts | NONE | DENIED |
| account_transfers | NONE | DENIED |
| account_value_anchors | NONE | DENIED |
| portfolio_income_goals | NONE | DENIED |
| trade_instructions | NONE | DENIED |
| system_controls | NONE | DENIED |
| config_documents | NONE | DENIED |
| config_change_proposals | NONE | DENIED |

---

## 5. hermes_staging_writer Grants

Unchanged from Phase 1A — staging-only:

| Table | Grants |
|-------|--------|
| hermes_research_intelligence | SELECT, INSERT, UPDATE |
| hermes_validation_findings | SELECT, INSERT, UPDATE |
| hermes_alerts | SELECT, INSERT, UPDATE |
| hermes_embedding_queue | SELECT, INSERT, UPDATE |
| hermes_memory_events | SELECT, INSERT, UPDATE |
| hermes_promotion_audit | SELECT only |

**No production table grants. No DELETE. No TRUNCATE.**

---

## 6. Hermes Staging Row Counts

| Table | Rows | Expected |
|-------|------|----------|
| hermes_research_intelligence | 0 | 0 |
| hermes_validation_findings | 0 | 0 |
| hermes_alerts | 0 | 0 |
| hermes_embedding_queue | 0 | 0 |
| hermes_memory_events | **1** | 1 (Phase 1B smoke row) |
| hermes_promotion_audit | 0 | 0 |

**Only the Phase 1B smoke row exists. No real Hermes research ingestion.**

---

## 7. Hermes Embeddings

```sql
SELECT source_type, COUNT(*) FROM content_embeddings WHERE source_type ILIKE '%hermes%';
-- (0 rows)
```

**Zero Hermes embeddings in content_embeddings: CONFIRMED**

---

## 8. Safety Confirmation

| Check | Status |
|-------|--------|
| Production table writes | **ZERO** |
| Broker access | **ZERO** |
| Proposal mutations | **ZERO** |
| paper_trades mutations | **ZERO** |
| Journal mutations | **ZERO** |
| Cron changes | **ZERO** |
| Service/daemon changes | **ZERO** |
| .env changes | **ZERO** |

---

## 9. Risks

None identified. Phase 1D was applied cleanly.

---

## 10. Corrective Action Needed

**NONE** — all checks pass.

---

## 11. Next Approval Gate

| Gate | Status |
|------|--------|
| Define 5 pilot Hermes agent workflows | NEEDS APPROVAL |
| Connect Hermes to DB views for contextual answers | NEEDS APPROVAL |
| Real Hermes research ingestion | NEEDS APPROVAL |
| Hermes agent orchestration dashboard | NEEDS APPROVAL |
