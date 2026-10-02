-- SearXNG Phase 19B Rollback — Remove staged source discovery candidates
-- Date: 2026-05-31
-- Target: exactly the five Phase 19B rows (ids 12–16), not later discovery rows.

BEGIN;

DELETE FROM hermes_research_intelligence
WHERE id IN (12, 13, 14, 15, 16)
  AND research_type = 'source_discovery'
  AND hermes_agent_name = 'source_discovery_agent'
  AND status = 'staged';

COMMIT;
