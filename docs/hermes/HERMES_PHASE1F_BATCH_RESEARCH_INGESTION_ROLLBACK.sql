-- Hermes Phase 1F Rollback: Remove batch research rows
-- Date: 2026-05-30
-- Removes Phase 1F rows (ids 2, 3, 4) from hermes_research_intelligence

DELETE FROM hermes_research_intelligence
WHERE id IN (2, 3, 4)
  AND source = 'hermes'
  AND status = 'staged';
