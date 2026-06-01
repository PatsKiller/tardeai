-- Phase 90 Rollback
BEGIN;
DELETE FROM llm_intelligence_cache WHERE section='hermes_source_discovery_TRX' AND metadata::text LIKE '%phase_90%';
DELETE FROM hermes_promotion_audit WHERE source_id=16 AND notes LIKE '%Phase 90%';
UPDATE hermes_research_intelligence SET status='staged', promoted_to_table=NULL WHERE id=16;
COMMIT;
