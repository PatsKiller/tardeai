-- Hermes Phase 22B Rollback — Remove staged research backlog items
-- Date: 2026-06-01

BEGIN;

DELETE FROM hermes_research_intelligence
WHERE research_type = 'research_backlog'
  AND hermes_agent_name = 'research_backlog_manager'
  AND status = 'staged';

COMMIT;
