-- Phase 48 Rollback
BEGIN;
DELETE FROM hermes_advisory_events WHERE source_table='hermes_research_intelligence' AND event_type='source_discovery_followup_staged';
DELETE FROM hermes_research_intelligence WHERE research_type='source_discovery_followup' AND tags @> ARRAY['phase_48C'];
COMMIT;
