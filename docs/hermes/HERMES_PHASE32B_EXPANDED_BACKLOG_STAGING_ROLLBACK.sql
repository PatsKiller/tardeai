-- Hermes Phase 32B Rollback — Remove expanded Librarian backlog items
-- Date: 2026-06-01

BEGIN;

DELETE FROM hermes_research_intelligence
WHERE research_type = 'research_backlog'
  AND hermes_agent_name = 'expanded_librarian_agent'
  AND tags @> ARRAY['phase_32B'];

COMMIT;
