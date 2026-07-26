-- 0002_roles.down.sql — rollback of the agentic_runtime least-privilege roles.
--
-- PREPARE-ONLY. Applied ONLY via apply.sh --apply. Revokes all grants and drops
-- the three roles. Safe to run repeatedly; uses IF EXISTS guards.

BEGIN;

-- Reverse default privileges first so the roles can be dropped cleanly.
ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
    REVOKE SELECT, INSERT ON TABLES FROM agentic_runtime_lab_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
    REVOKE SELECT, INSERT ON TABLES FROM agentic_runtime_shadow_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
    REVOKE SELECT ON TABLES FROM agentic_runtime_reader;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_lab_rw') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA agentic_runtime FROM agentic_runtime_lab_rw;
        REVOKE ALL ON SCHEMA agentic_runtime FROM agentic_runtime_lab_rw;
        DROP ROLE agentic_runtime_lab_rw;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_shadow_rw') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA agentic_runtime FROM agentic_runtime_shadow_rw;
        REVOKE ALL ON SCHEMA agentic_runtime FROM agentic_runtime_shadow_rw;
        DROP ROLE agentic_runtime_shadow_rw;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_reader') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA agentic_runtime FROM agentic_runtime_reader;
        REVOKE ALL ON SCHEMA agentic_runtime FROM agentic_runtime_reader;
        DROP ROLE agentic_runtime_reader;
    END IF;
END;
$$;

COMMIT;
