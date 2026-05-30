-- Hermes Phase 1A: Roles and Grants (requires postgres superuser)
-- Date: 2026-05-30
-- Purpose: Create group roles and least-privilege grants on hermes_* tables only.
-- Rollback: docs/hermes/HERMES_PHASE1A_DB_ROLES_ROLLBACK.sql

BEGIN;

-- ============================================================
-- 1. CREATE GROUP ROLES (NOLOGIN — no passwords, no login)
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_readonly') THEN
        CREATE ROLE hermes_readonly NOLOGIN;
        RAISE NOTICE 'Created role: hermes_readonly (NOLOGIN)';
    ELSE
        RAISE NOTICE 'Role hermes_readonly already exists';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_staging_writer') THEN
        CREATE ROLE hermes_staging_writer NOLOGIN;
        RAISE NOTICE 'Created role: hermes_staging_writer (NOLOGIN)';
    ELSE
        RAISE NOTICE 'Role hermes_staging_writer already exists';
    END IF;
END
$$;

-- ============================================================
-- 2. GRANTS: hermes_readonly — SELECT only on hermes_* tables
-- ============================================================

GRANT USAGE ON SCHEMA public TO hermes_readonly;

GRANT SELECT ON hermes_research_intelligence TO hermes_readonly;
GRANT SELECT ON hermes_validation_findings TO hermes_readonly;
GRANT SELECT ON hermes_alerts TO hermes_readonly;
GRANT SELECT ON hermes_embedding_queue TO hermes_readonly;
GRANT SELECT ON hermes_memory_events TO hermes_readonly;
GRANT SELECT ON hermes_promotion_audit TO hermes_readonly;

-- ============================================================
-- 3. GRANTS: hermes_staging_writer — INSERT/UPDATE/SELECT on hermes_* tables
--    SELECT granted because UPDATE requires reading the row to verify changes.
--    No DELETE. No TRUNCATE. No production tables.
-- ============================================================

GRANT USAGE ON SCHEMA public TO hermes_staging_writer;

GRANT SELECT, INSERT, UPDATE ON hermes_research_intelligence TO hermes_staging_writer;
GRANT SELECT, INSERT, UPDATE ON hermes_validation_findings TO hermes_staging_writer;
GRANT SELECT, INSERT, UPDATE ON hermes_alerts TO hermes_staging_writer;
GRANT SELECT, INSERT, UPDATE ON hermes_embedding_queue TO hermes_staging_writer;
GRANT SELECT, INSERT, UPDATE ON hermes_memory_events TO hermes_staging_writer;
-- promotion_audit: written by promotion script only, not by Hermes agent
-- hermes_staging_writer does NOT get write access to hermes_promotion_audit
GRANT SELECT ON hermes_promotion_audit TO hermes_staging_writer;

-- ============================================================
-- 4. SEQUENCE GRANTS: hermes_staging_writer needs USAGE on hermes_* sequences
--    for BIGSERIAL INSERT to work
-- ============================================================

GRANT USAGE, SELECT ON SEQUENCE hermes_research_intelligence_id_seq TO hermes_staging_writer;
GRANT USAGE, SELECT ON SEQUENCE hermes_validation_findings_id_seq TO hermes_staging_writer;
GRANT USAGE, SELECT ON SEQUENCE hermes_alerts_id_seq TO hermes_staging_writer;
GRANT USAGE, SELECT ON SEQUENCE hermes_embedding_queue_id_seq TO hermes_staging_writer;
GRANT USAGE, SELECT ON SEQUENCE hermes_memory_events_id_seq TO hermes_staging_writer;
-- No sequence grant for hermes_promotion_audit (writer doesn't insert)

COMMIT;
