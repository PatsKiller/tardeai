-- SearXNG Phase 19B Rollback — Remove staged source discovery candidates
-- Date: 2026-05-31
-- Target: hermes_research_intelligence rows with research_type='source_discovery'

BEGIN;

DELETE FROM hermes_research_intelligence
WHERE research_type = 'source_discovery'
  AND hermes_agent_name = 'source_discovery_agent'
  AND status = 'staged';

COMMIT;
