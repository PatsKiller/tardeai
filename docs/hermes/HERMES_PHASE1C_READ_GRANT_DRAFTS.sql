-- Hermes Phase 1C: Read Grant Drafts
-- DRAFT ONLY — DO NOT APPLY until operator approves
-- Date: 2026-05-30
-- Purpose: Grant hermes_readonly SELECT on safe views only (not direct tables)

-- Prerequisites:
--   1. Views from HERMES_PHASE1C_SAFE_VIEW_DRAFTS.sql must be created first
--   2. hermes_readonly role must exist (created in Phase 1A)

BEGIN;

-- Grant SELECT on safe views
GRANT SELECT ON hermes_v_ticker_context TO hermes_readonly;
GRANT SELECT ON hermes_v_proposal_context TO hermes_readonly;
GRANT SELECT ON hermes_v_trade_reflection_context TO hermes_readonly;
GRANT SELECT ON hermes_v_news_research_context TO hermes_readonly;
GRANT SELECT ON hermes_v_agent_results_context TO hermes_readonly;
GRANT SELECT ON hermes_v_pipeline_health_context TO hermes_readonly;
GRANT SELECT ON hermes_v_rag_context_metadata TO hermes_readonly;
GRANT SELECT ON hermes_v_portfolio_context TO hermes_readonly;

-- Direct table grants for tables with no sensitive columns
-- (these tables have no account, credential, or personal data)
GRANT SELECT ON ticker_snapshot_daily TO hermes_readonly;
GRANT SELECT ON news_articles TO hermes_readonly;
GRANT SELECT ON intelligence_entities TO hermes_readonly;
GRANT SELECT ON content_entity_links TO hermes_readonly;
GRANT SELECT ON research_insights TO hermes_readonly;
GRANT SELECT ON fused_signals TO hermes_readonly;
GRANT SELECT ON deep_overnight_llm_results TO hermes_readonly;
GRANT SELECT ON llm_intelligence_cache TO hermes_readonly;
GRANT SELECT ON agent_intelligence_rules TO hermes_readonly;
GRANT SELECT ON market_quotes TO hermes_readonly;
GRANT SELECT ON indicator_confluence_cache TO hermes_readonly;
GRANT SELECT ON catalyst_events TO hermes_readonly;
GRANT SELECT ON trade_ai_scans TO hermes_readonly;
GRANT SELECT ON ticker_strategy_classifications TO hermes_readonly;
GRANT SELECT ON strategy_performance_snapshots TO hermes_readonly;
GRANT SELECT ON strategy_lesson_rollup TO hermes_readonly;
GRANT SELECT ON strategy_registry TO hermes_readonly;
GRANT SELECT ON finviz_screeners TO hermes_readonly;
GRANT SELECT ON paper_trade_multi_reviews TO hermes_readonly;
GRANT SELECT ON proposal_outcome_chain TO hermes_readonly;
GRANT SELECT ON proposal_event_log TO hermes_readonly;
GRANT SELECT ON paper_execution_quality TO hermes_readonly;
GRANT SELECT ON youtube_transcripts TO hermes_readonly;
GRANT SELECT ON sec_form4 TO hermes_readonly;
GRANT SELECT ON fred_economic_series TO hermes_readonly;
GRANT SELECT ON social_posts TO hermes_readonly;
GRANT SELECT ON social_sentiment_history TO hermes_readonly;
GRANT SELECT ON recovery_outcome_log TO hermes_readonly;
GRANT SELECT ON portfolio_snapshots TO hermes_readonly;
GRANT SELECT ON portfolio_intelligence_events TO hermes_readonly;
GRANT SELECT ON system_health_checks TO hermes_readonly;
GRANT SELECT ON system_health_events TO hermes_readonly;
GRANT SELECT ON alert_events TO hermes_readonly;
GRANT SELECT ON alert_effectiveness TO hermes_readonly;
GRANT SELECT ON notification_log TO hermes_readonly;
GRANT SELECT ON daily_system_metrics TO hermes_readonly;
GRANT SELECT ON confidence_calibration_history TO hermes_readonly;

COMMIT;
