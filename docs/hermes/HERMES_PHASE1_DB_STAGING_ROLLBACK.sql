-- Hermes Phase 1 ROLLBACK: Remove all staging tables and roles
-- Date: 2026-05-30
-- Rolls back: 20260530_hermes_phase1_staging_tables.sql

BEGIN;

-- Drop tables (CASCADE handles FK references between hermes tables)
DROP TABLE IF EXISTS hermes_promotion_audit CASCADE;
DROP TABLE IF EXISTS hermes_embedding_queue CASCADE;
DROP TABLE IF EXISTS hermes_alerts CASCADE;
DROP TABLE IF EXISTS hermes_memory_events CASCADE;
DROP TABLE IF EXISTS hermes_validation_findings CASCADE;
DROP TABLE IF EXISTS hermes_research_intelligence CASCADE;

-- Drop roles (only if no other objects depend on them)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_staging_writer') THEN
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM hermes_staging_writer;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM hermes_staging_writer;
        DROP ROLE hermes_staging_writer;
        RAISE NOTICE 'Dropped role: hermes_staging_writer';
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_readonly') THEN
        REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM hermes_readonly;
        DROP ROLE hermes_readonly;
        RAISE NOTICE 'Dropped role: hermes_readonly';
    END IF;
END
$$;

COMMIT;
