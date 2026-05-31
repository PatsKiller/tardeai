-- Phase 4B Rollback: Remove promoted Hermes rows from llm_intelligence_cache
DELETE FROM llm_intelligence_cache WHERE section IN (
    'hermes_trade_reflection_APPS',
    'hermes_ticker_thesis_challenge_INFU',
    'hermes_ticker_thesis_challenge_FLYW'
);

-- Reset source rows
UPDATE hermes_research_intelligence SET status='staged', promoted_to_table=NULL, promoted_to_id=NULL
WHERE id IN (4, 5, 1) AND status='promoted';

-- Remove audit records
DELETE FROM hermes_promotion_audit WHERE source_table='hermes_research_intelligence' AND source_id IN (1, 4, 5);
