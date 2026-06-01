-- Phase 70 Rollback
BEGIN;
DELETE FROM hermes_advisory_events WHERE event_type LIKE 'ops_backlog_%';
DELETE FROM hermes_research_intelligence WHERE research_type='ops_backlog' AND tags @> ARRAY['phase_70'];
COMMIT;
