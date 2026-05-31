-- Phase 7B Rollback
DELETE FROM hermes_validation_findings WHERE id IN (2, 3, 4) AND source='hermes' AND status='open';
