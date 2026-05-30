-- Hermes Phase 1A ROLLBACK: Revoke grants and drop roles
-- Date: 2026-05-30
-- Rolls back: 20260530_hermes_phase1a_roles_and_grants.sql

BEGIN;

-- Revoke all hermes_staging_writer grants
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_staging_writer') THEN
        REVOKE ALL PRIVILEGES ON hermes_research_intelligence FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON hermes_validation_findings FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON hermes_alerts FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON hermes_embedding_queue FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON hermes_memory_events FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON hermes_promotion_audit FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON SEQUENCE hermes_research_intelligence_id_seq FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON SEQUENCE hermes_validation_findings_id_seq FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON SEQUENCE hermes_alerts_id_seq FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON SEQUENCE hermes_embedding_queue_id_seq FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON SEQUENCE hermes_memory_events_id_seq FROM hermes_staging_writer;
        REVOKE USAGE ON SCHEMA public FROM hermes_staging_writer;
        DROP ROLE hermes_staging_writer;
        RAISE NOTICE 'Dropped role: hermes_staging_writer';
    END IF;
END
$$;

-- Revoke all hermes_readonly grants
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_readonly') THEN
        REVOKE ALL PRIVILEGES ON hermes_research_intelligence FROM hermes_readonly;
        REVOKE ALL PRIVILEGES ON hermes_validation_findings FROM hermes_readonly;
        REVOKE ALL PRIVILEGES ON hermes_alerts FROM hermes_readonly;
        REVOKE ALL PRIVILEGES ON hermes_embedding_queue FROM hermes_readonly;
        REVOKE ALL PRIVILEGES ON hermes_memory_events FROM hermes_readonly;
        REVOKE ALL PRIVILEGES ON hermes_promotion_audit FROM hermes_readonly;
        REVOKE USAGE ON SCHEMA public FROM hermes_readonly;
        DROP ROLE hermes_readonly;
        RAISE NOTICE 'Dropped role: hermes_readonly';
    END IF;
END
$$;

COMMIT;
