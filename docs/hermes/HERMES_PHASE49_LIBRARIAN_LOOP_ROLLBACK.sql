-- Phase 49 Rollback — Remove autonomous librarian loop rows
BEGIN;
DELETE FROM hermes_advisory_events WHERE event_type='librarian_backlog_created';
DELETE FROM hermes_research_intelligence WHERE hermes_agent_name='autonomous_librarian_loop' AND tags @> ARRAY['phase_49'];
COMMIT;
