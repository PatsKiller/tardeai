-- 0002_roles.up.sql — least-privilege roles for the agentic_runtime schema.
--
-- PREPARE-ONLY. This file is applied ONLY via migrations/agentic_runtime/apply.sh
-- with an explicit --apply flag against an isolated LAB/SHADOW database, after the
-- permission review is accepted. It creates three narrowly-scoped roles and grants
-- them access to NOTHING outside the agentic_runtime schema. It never touches
-- trading, broker, account, position, approval, 2FA, or production-config tables.
--
-- Passwords are intentionally NOT set here (no secret material in the repository).
-- The operator sets them out-of-band from the secret store after apply.

BEGIN;

-- Roles are created idempotently and WITHOUT any elevated attribute. The runtime
-- identity check (scripts/agent_runtime/persistence.py) refuses to write unless the
-- connected role is one of the *_rw roles below and holds none of
-- superuser/createdb/createrole/replication/bypassrls.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_lab_rw') THEN
        CREATE ROLE agentic_runtime_lab_rw LOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_shadow_rw') THEN
        CREATE ROLE agentic_runtime_shadow_rw LOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_runtime_reader') THEN
        CREATE ROLE agentic_runtime_reader LOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
END;
$$;

-- Schema is private: no ambient PUBLIC access, and no role may create objects in it.
REVOKE ALL ON SCHEMA agentic_runtime FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA agentic_runtime FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- Writer roles (LAB + SHADOW): append evidence, mutate only the run-control row.
-- ---------------------------------------------------------------------------
-- USAGE lets them resolve objects in the schema but not create.
GRANT USAGE ON SCHEMA agentic_runtime TO agentic_runtime_lab_rw, agentic_runtime_shadow_rw;
REVOKE CREATE ON SCHEMA agentic_runtime FROM agentic_runtime_lab_rw, agentic_runtime_shadow_rw;

-- agent_runs is the single mutable control row (status/counters/checkpoint).
GRANT SELECT, INSERT, UPDATE ON agentic_runtime.agent_runs
    TO agentic_runtime_lab_rw, agentic_runtime_shadow_rw;

-- Evidence tables are append-only (BEFORE UPDATE OR DELETE triggers reject writes);
-- grant only SELECT + INSERT and never DELETE. Defense in depth alongside the trigger.
GRANT SELECT, INSERT ON
    agentic_runtime.agent_artifacts,
    agentic_runtime.agent_tool_calls,
    agentic_runtime.agent_reviews,
    agentic_runtime.agent_scores,
    agentic_runtime.kb_lessons,
    agentic_runtime.kb_cases,
    agentic_runtime.kb_chunks
    TO agentic_runtime_lab_rw, agentic_runtime_shadow_rw;

-- Future tables in this schema (if a reviewed migration adds one) default to the
-- same SELECT+INSERT posture for the writers.
ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
    GRANT SELECT, INSERT ON TABLES TO agentic_runtime_lab_rw, agentic_runtime_shadow_rw;

-- ---------------------------------------------------------------------------
-- Reader role (Command Center): read-only, this schema only.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA agentic_runtime TO agentic_runtime_reader;
REVOKE CREATE ON SCHEMA agentic_runtime FROM agentic_runtime_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA agentic_runtime TO agentic_runtime_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA agentic_runtime
    GRANT SELECT ON TABLES TO agentic_runtime_reader;

-- Belt-and-braces: the Command Center reader must never write.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA agentic_runtime FROM agentic_runtime_reader;

COMMENT ON ROLE agentic_runtime_lab_rw IS 'LAB writer: agentic_runtime schema only; no broker/account/approval/2FA/config authority.';
COMMENT ON ROLE agentic_runtime_shadow_rw IS 'SHADOW writer: agentic_runtime schema only; no broker/account/approval/2FA/config authority.';
COMMENT ON ROLE agentic_runtime_reader IS 'Command Center read-only: SELECT on agentic_runtime schema only; no trading data.';

COMMIT;
