-- CIO prospect data foundation, P1 (2026-10-22): the cio_prospect store.
--
-- NEEDS OPERATOR. Written, not applied. AGENTS.md §26 (18.0.0, ACTIVE) and §17: a new authoritative Postgres store is
-- an operator decision, and this file runs only after BOTH grants are recorded:
--   (1) the registry row `cio_prospect` granted (config/data_source_authority.json proposed_domains[] -> domains[],
--       via scripts/lib/data_dictionary.promote), and
--   (2) the P1 migration grant naming this file and its sha256 (scripts/cio_prospect_migration_plan.py prints both).
-- Until then nothing reads or writes these tables: InstrumentRecordStore's Postgres dual-write is inert
-- (scripts/lib/cio_instrument_record.py prospect_store_status()), and the data-broker projection `cio_prospect`
-- (scripts/lib/data_broker/cio_prospect.py) serves the shadow build, labelled source=shadow, never as the store.
--
-- Architecture: docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §4 (storage sketch) and §7 (P1 Shadow).
-- Dictionary: docs/architecture/DATA_DICTIONARY.md `CIOProspect`.
--
-- Two NEW tables. Nothing existing is altered, so this migration is additive by construction.
--
--   cio_prospect          one row per security_guid: the CIO's current per-security truth (InstrumentRecord@v1
--                         extended, §13.5). Writer: InstrumentRecordStore ONLY (writer column is CHECKed).
--   cio_prospect_events   append-only change log, same writer. A trigger refuses UPDATE, DELETE and TRUNCATE for
--                         every role, including the owner (§0 rule 6: never delete; append a compensating event).
--                         One row per fact, idempotent by (security_guid, event_key): record changes (rev:<n>) and
--                         the position lifecycle — origin attributed, entry fill, every observed stop change,
--                         conviction/stance changes while held, excursion, exit fill + cause, exit review, re-entry
--                         advice (operator 2026-10-22, NAVN: "all on the same data backend").
--
-- MBI_BEHAVIOR = 0: no column holds a size, an order, a stop, a weight or an execution. Stance is posture and
-- priority only; next_trigger holds a reference level, never an order (§0 rule 1, §26.1).
--
-- Idempotent: CREATE ... IF NOT EXISTS; triggers are created only when absent (no DROP anywhere).
-- Plan (agent or operator, no DB contact):  .venv/bin/python scripts/cio_prospect_migration_plan.py
-- Apply (operator):   psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_cio_prospect.sql
-- Verify (operator):  psql "$DB" -c "SELECT to_regclass('public.cio_prospect'), to_regclass('public.cio_prospect_events')"
-- Reverse (operator): migrations/2026_10_22_cio_prospect.down.sql (archives by rename; never drops).

BEGIN;

CREATE TABLE IF NOT EXISTS cio_prospect (
    security_guid          UUID PRIMARY KEY,
    issuer_guid            UUID NOT NULL,
    symbol                 TEXT NOT NULL,
    subject_key            TEXT,
    aliases                JSONB NOT NULL DEFAULT '{}'::jsonb,
    stage                  TEXT NOT NULL,
    stage_changed_at       TIMESTAMPTZ,
    stage_evidence         JSONB,
    conviction             NUMERIC(5,2) NOT NULL,
    conviction_components  JSONB NOT NULL DEFAULT '{}'::jsonb,
    stance                 TEXT NOT NULL,
    catalyst_grade         JSONB,
    next_trigger           JSONB,
    whats_missing          JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_action            JSONB,
    thesis_ref             TEXT,
    research               JSONB,
    position_ref           JSONB,
    watchlist              JSONB,
    stage_phase            TEXT,
    origin                 JSONB,
    position_lifecycle     JSONB,
    post_exit_review       JSONB,
    reentry_advice         JSONB,
    conflicts              JSONB NOT NULL DEFAULT '[]'::jsonb,
    cognition              JSONB,
    provenance             JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_at            TIMESTAMPTZ NOT NULL,
    expires_at             TIMESTAMPTZ NOT NULL,
    as_of                  TIMESTAMPTZ NOT NULL,
    writer                 TEXT NOT NULL,
    revision               BIGINT NOT NULL,
    CONSTRAINT cio_prospect_writer_ck CHECK (writer = 'InstrumentRecordStore'),
    CONSTRAINT cio_prospect_stage_ck CHECK (stage IN (
        'watching', 'setup_forming', 'actionable', 'proposed', 'held', 'exit', 're_entry')),
    CONSTRAINT cio_prospect_phase_ck CHECK (stage_phase IS NULL OR stage_phase IN ('exit_review', 're_entry_watch')),
    CONSTRAINT cio_prospect_origin_ck CHECK (origin IS NULL OR origin->>'classification' IN (
        'internal', 'operator_initiated')),
    CONSTRAINT cio_prospect_stance_ck CHECK (stance IN (
        'BUY_SETUP', 'ADD', 'HOLD', 'TRIM_REVIEW', 'EXIT_REVIEW', 'WATCH', 'AVOID')),
    CONSTRAINT cio_prospect_conviction_ck CHECK (conviction >= 0 AND conviction <= 100),
    CONSTRAINT cio_prospect_revision_ck CHECK (revision >= 1),
    CONSTRAINT cio_prospect_expiry_ck CHECK (expires_at >= evidence_at),
    CONSTRAINT cio_prospect_components_ck CHECK (jsonb_typeof(conviction_components) = 'object'),
    CONSTRAINT cio_prospect_conflicts_ck CHECK (jsonb_typeof(conflicts) = 'array'),
    CONSTRAINT cio_prospect_missing_ck CHECK (jsonb_typeof(whats_missing) = 'array'),
    CONSTRAINT cio_prospect_aliases_ck CHECK (jsonb_typeof(aliases) = 'object'),
    CONSTRAINT cio_prospect_provenance_ck CHECK (jsonb_typeof(provenance) = 'object')
);

CREATE INDEX IF NOT EXISTS cio_prospect_issuer_idx ON cio_prospect (issuer_guid);
CREATE INDEX IF NOT EXISTS cio_prospect_symbol_idx ON cio_prospect (symbol);
CREATE INDEX IF NOT EXISTS cio_prospect_stage_conviction_idx ON cio_prospect (stage, conviction DESC);
CREATE INDEX IF NOT EXISTS cio_prospect_expires_idx ON cio_prospect (expires_at);

COMMENT ON TABLE cio_prospect IS
    'CIO prospect: one row per security_guid, the single per-security truth (AGENTS.md section 26). '
    'Written only by InstrumentRecordStore (scripts/lib/cio_instrument_record.py). Conflicts are shown, never resolved '
    'silently. MBI_BEHAVIOR = 0: no size, order, stop or weight.';

CREATE TABLE IF NOT EXISTS cio_prospect_events (
    id             BIGSERIAL PRIMARY KEY,
    security_guid  UUID NOT NULL,
    at             TIMESTAMPTZ NOT NULL,
    writer         TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    event_key      TEXT NOT NULL,
    change         JSONB NOT NULL,
    evidence       JSONB,
    revision       BIGINT NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cio_prospect_events_writer_ck CHECK (writer = 'InstrumentRecordStore'),
    CONSTRAINT cio_prospect_events_type_ck CHECK (event_type IN (
        'mint', 'update', 'stage_change', 'conflict_opened', 'conflict_resolved', 'rollback',
        'origin_attributed', 'entry_fill', 'stop_change', 'conviction_change', 'excursion', 'exit_fill',
        'exit_review', 'reentry_advice')),
    CONSTRAINT cio_prospect_events_change_ck CHECK (jsonb_typeof(change) = 'object'),
    CONSTRAINT cio_prospect_events_key_uq UNIQUE (security_guid, event_key)
);

CREATE INDEX IF NOT EXISTS cio_prospect_events_guid_idx ON cio_prospect_events (security_guid, id);

COMMENT ON TABLE cio_prospect_events IS
    'Append-only change log for cio_prospect (same writer). UPDATE/DELETE/TRUNCATE refused by trigger.';

CREATE OR REPLACE FUNCTION cio_prospect_events_refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'cio_prospect_events is append-only: % refused', TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'Append a compensating event instead (AGENTS.md section 0 rule 6: never delete).';
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'cio_prospect_events_no_update_delete'
                   AND tgrelid = 'cio_prospect_events'::regclass) THEN
        CREATE TRIGGER cio_prospect_events_no_update_delete
            BEFORE UPDATE OR DELETE ON cio_prospect_events
            FOR EACH ROW EXECUTE FUNCTION cio_prospect_events_refuse_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'cio_prospect_events_no_truncate'
                   AND tgrelid = 'cio_prospect_events'::regclass) THEN
        CREATE TRIGGER cio_prospect_events_no_truncate
            BEFORE TRUNCATE ON cio_prospect_events
            FOR EACH STATEMENT EXECUTE FUNCTION cio_prospect_events_refuse_mutation();
    END IF;
END
$$;

-- A prospect row is never deleted either: a security leaves by stage/expiry, and its history stays.
CREATE OR REPLACE FUNCTION cio_prospect_refuse_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'cio_prospect rows are never deleted: % refused', TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'Move the stage or let expires_at lapse (AGENTS.md section 0 rule 6).';
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'cio_prospect_no_delete'
                   AND tgrelid = 'cio_prospect'::regclass) THEN
        CREATE TRIGGER cio_prospect_no_delete
            BEFORE DELETE ON cio_prospect
            FOR EACH ROW EXECUTE FUNCTION cio_prospect_refuse_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'cio_prospect_no_truncate'
                   AND tgrelid = 'cio_prospect'::regclass) THEN
        CREATE TRIGGER cio_prospect_no_truncate
            BEFORE TRUNCATE ON cio_prospect
            FOR EACH STATEMENT EXECUTE FUNCTION cio_prospect_refuse_delete();
    END IF;
END
$$;

-- Least privilege for the application role (scripts/session13_db.py DB_USER = trade_ai): upsert the current row,
-- append events, read both. No DELETE, no TRUNCATE, no DDL. PUBLIC gets nothing.
REVOKE ALL ON cio_prospect, cio_prospect_events FROM PUBLIC;
REVOKE ALL ON SEQUENCE cio_prospect_events_id_seq FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON cio_prospect TO trade_ai;
GRANT SELECT, INSERT ON cio_prospect_events TO trade_ai;
GRANT USAGE ON SEQUENCE cio_prospect_events_id_seq TO trade_ai;

COMMIT;
