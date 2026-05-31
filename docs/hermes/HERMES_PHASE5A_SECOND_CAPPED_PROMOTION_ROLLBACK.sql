-- Phase 5A Rollback
DELETE FROM llm_intelligence_cache WHERE section IN (
    'hermes_ticker_thesis_challenge_SPRC',
    'hermes_news_research_reframe_SCHD',
    'hermes_trade_reflection_ASPN',
    'hermes_pipeline_quality_validation_SYSTEM'
);
UPDATE hermes_research_intelligence SET status='staged', promoted_to_table=NULL, promoted_to_id=NULL
WHERE id IN (2, 3, 6, 7) AND status='promoted';
DELETE FROM hermes_promotion_audit WHERE source_table='hermes_research_intelligence' AND source_id IN (2, 3, 6, 7);
