-- Hermes Phase 1B Rollback: Remove smoke test row only
-- Date: 2026-05-30
-- Removes exactly the Phase 1B smoke test row from hermes_memory_events

DELETE FROM hermes_memory_events
WHERE id = 2
  AND source = 'hermes'
  AND hermes_agent_name = 'chief_hermes_coordinator'
  AND event_type = 'agent_state_change'
  AND (metadata_json->>'test')::text = 'true'
  AND (metadata_json->>'phase')::text = '1B';
