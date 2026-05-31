-- Phase 3C Rollback
DELETE FROM hermes_research_intelligence WHERE id IN (8, 9) AND source='hermes' AND status='staged';
