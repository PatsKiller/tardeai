-- Hermes Phase 1E Rollback: Remove first research ingestion row
-- Date: 2026-05-30

DELETE FROM hermes_research_intelligence
WHERE id = 1
  AND source = 'hermes'
  AND hermes_agent_name = 'ticker_research_agent'
  AND research_type = 'ticker_thesis_challenge'
  AND symbol = 'FLYW'
  AND status = 'staged';
