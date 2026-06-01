-- Phase 79 Rollback
BEGIN;
DELETE FROM hermes_advisory_events WHERE event_type='source_discovery_followup_staged' AND source_table='hermes_research_intelligence' AND source_id IN (SELECT id FROM hermes_research_intelligence WHERE tags @> ARRAY['phase_79C']);
DELETE FROM hermes_research_intelligence WHERE tags @> ARRAY['phase_79C'];
COMMIT;
