-- Hermes Phase 1H Rollback: Remove hardened batch rows
-- Date: 2026-05-30
DELETE FROM hermes_research_intelligence
WHERE id IN (5, 6, 7) AND source = 'hermes' AND status = 'staged';
