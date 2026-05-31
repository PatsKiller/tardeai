-- Phase 8B Rollback: Remove portfolio reflection rows
DELETE FROM hermes_validation_findings WHERE evidence_json->>'run_id' LIKE 'phase8a_portfolio_reflection_%' AND source='hermes';
