-- Release Train v2, Phase 1 (2026-10-21): the release queue store.
--
-- NEEDS OPERATOR. Written, not applied. Nothing in Phase 1 writes these tables; the read path
-- (scripts/lib/release_train_queue.py, GET /api/v2/coordination/release-train*) reports the store as
-- UNAVAILABLE / not_migrated until this runs, and never shows zero in its place.
--
-- Plan: Release Train v2 (joyful-skipping-wilkes), Phase 1 "Queue store". Design: enhanced design section 4
-- ("a transactional queue with an append-only event history and rebuildable read models") and section 9 ("persist
-- the transaction and outbox in one authoritative store; mirrors and monthly reports are derived projections").
--
-- Two NEW tables. Nothing existing is altered, so this migration is additive by construction.
--
--   release_queue_events   the ONE authoritative store. Append-only: a trigger refuses UPDATE, DELETE and
--                          TRUNCATE for every role, including the owner. Each row is a TrainEvent@v1
--                          (config/schemas/release_train/train_event.v1.schema.json); seq is the total order.
--                          Writer: scripts/lib/release_train_queue.py append_event() (no production caller in Phase 1).
--   release_queue          a projection, one row per PR, rebuildable at any time from release_queue_events by
--                          scripts/lib/release_train_queue.py rebuild_projection(). It is never a second writer of
--                          truth: if it disagrees with the events, the events win and the projection is rebuilt.
--
-- Idempotent: CREATE ... IF NOT EXISTS; the triggers are created only when absent (no DROP anywhere).
-- Apply (operator):   psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_release_queue.sql
-- Verify (operator):  psql "$DB" -c "SELECT to_regclass('public.release_queue_events'), to_regclass('public.release_queue')"
--                     then GET /api/v2/coordination/release-train shows store.value.state = "OK".
-- Reverse (operator): migrations/2026_10_21_release_queue.down.sql (archives by rename; never drops).

BEGIN;

CREATE TABLE IF NOT EXISTS release_queue_events (
    seq              BIGSERIAL PRIMARY KEY,
    event_id         TEXT NOT NULL,
    schema           TEXT NOT NULL DEFAULT 'TrainEvent@v1',
    event_type       TEXT NOT NULL,
    subject_kind     TEXT NOT NULL,
    subject_id       TEXT NOT NULL,
    pr_number        INTEGER,
    train_id         TEXT,
    state_after      TEXT,
    actor            TEXT NOT NULL,
    policy_version   TEXT,
    epoch            BIGINT,
    idempotency_key  TEXT,
    occurred_at      TIMESTAMPTZ NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs    JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT release_queue_events_event_id_uq UNIQUE (event_id),
    CONSTRAINT release_queue_events_idem_uq UNIQUE (idempotency_key),
    CONSTRAINT release_queue_events_schema_ck CHECK (schema = 'TrainEvent@v1'),
    CONSTRAINT release_queue_events_subject_kind_ck CHECK (subject_kind IN ('pr', 'train', 'control')),
    CONSTRAINT release_queue_events_pr_subject_ck
        CHECK (subject_kind <> 'pr' OR (pr_number IS NOT NULL AND subject_id = 'pr:' || pr_number::text)),
    CONSTRAINT release_queue_events_train_subject_ck
        CHECK (subject_kind <> 'train' OR (train_id IS NOT NULL AND subject_id = 'train:' || train_id)),
    CONSTRAINT release_queue_events_payload_ck CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT release_queue_events_refs_ck CHECK (jsonb_typeof(evidence_refs) = 'array'),
    CONSTRAINT release_queue_events_state_ck CHECK (state_after IS NULL OR state_after IN (
        'submitted', 'classified', 'ready', 'held', 'needs_operator', 'blocked', 'selected', 'integrating',
        'qualified', 'waiting_window', 'merged', 'promoting', 'released', 'observing', 'rolled_back',
        'rollback_failed', 'superseded', 'quarantined', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS release_queue_events_pr_seq_idx ON release_queue_events (pr_number, seq)
    WHERE pr_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS release_queue_events_train_seq_idx ON release_queue_events (train_id, seq)
    WHERE train_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS release_queue_events_type_seq_idx ON release_queue_events (event_type, seq);

COMMENT ON TABLE release_queue_events IS
    'Release Train v2 append-only event store (TrainEvent@v1). UPDATE/DELETE/TRUNCATE refused by trigger. '
    'Authoritative; release_queue is a projection rebuilt from it.';

-- Append-only enforcement. A trigger, not a GRANT, so it binds the table owner too.
CREATE OR REPLACE FUNCTION release_queue_events_refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'release_queue_events is append-only: % refused', TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'Append a compensating TrainEvent@v1 instead (AGENTS.md section 0 rule 6: never delete).';
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'release_queue_events_no_update_delete'
                   AND tgrelid = 'release_queue_events'::regclass) THEN
        CREATE TRIGGER release_queue_events_no_update_delete
            BEFORE UPDATE OR DELETE ON release_queue_events
            FOR EACH ROW EXECUTE FUNCTION release_queue_events_refuse_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'release_queue_events_no_truncate'
                   AND tgrelid = 'release_queue_events'::regclass) THEN
        CREATE TRIGGER release_queue_events_no_truncate
            BEFORE TRUNCATE ON release_queue_events
            FOR EACH STATEMENT EXECUTE FUNCTION release_queue_events_refuse_mutation();
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS release_queue (
    pr_number        INTEGER PRIMARY KEY,
    repo             TEXT NOT NULL,
    head_sha         TEXT,
    state            TEXT NOT NULL,
    risk_class       TEXT,
    risk_reasons     JSONB NOT NULL DEFAULT '[]'::jsonb,
    agent            TEXT,
    depends_on       JSONB NOT NULL DEFAULT '[]'::jsonb,
    intended_window  TEXT,
    blocker          TEXT,
    next_action      TEXT,
    train_id         TEXT,
    submitted_at     TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL,
    last_event_seq   BIGINT NOT NULL REFERENCES release_queue_events (seq),
    projected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT release_queue_risk_ck
        CHECK (risk_class IS NULL OR risk_class IN ('eligible', 'needs_operator', 'held', 'blocked')),
    CONSTRAINT release_queue_window_ck
        CHECK (intended_window IS NULL OR intended_window IN ('00:00', '06:00', '08:00', '18:00')),
    CONSTRAINT release_queue_state_ck CHECK (state IN (
        'submitted', 'classified', 'ready', 'held', 'needs_operator', 'blocked', 'selected', 'integrating',
        'qualified', 'waiting_window', 'merged', 'promoting', 'released', 'observing', 'rolled_back',
        'rollback_failed', 'superseded', 'quarantined', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS release_queue_state_idx ON release_queue (state);

COMMENT ON TABLE release_queue IS
    'Release Train v2 queue projection, one row per PR, rebuildable from release_queue_events '
    '(scripts/lib/release_train_queue.py rebuild_projection). Never an independent source of truth.';

COMMIT;
