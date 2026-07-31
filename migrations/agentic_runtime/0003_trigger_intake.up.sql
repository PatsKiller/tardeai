-- 0003_trigger_intake.up.sql — governed SHADOW trigger intake queue + source cursors.
--
-- PREPARE-ONLY. Applied via migrations/agentic_runtime/apply.sh with --apply against
-- an isolated LAB/SHADOW database. Queue rows are mutable control state; payloads are
-- immutable once enqueued. No broker/account/approval authority.

BEGIN;

CREATE TABLE agentic_runtime.trigger_intake (
    intake_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    job_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    source_timestamp TIMESTAMPTZ NOT NULL,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    state TEXT NOT NULL CHECK (state IN (
        'QUEUED', 'LEASED', 'COMPLETED', 'REFUSED_STALE', 'FAILED'
    )),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_outcome TEXT,
    last_run_id TEXT,
    completed_at TIMESTAMPTZ,
    UNIQUE (agent_id, trigger_kind, dedup_key)
);

CREATE INDEX trigger_intake_agent_state_enqueued_idx
    ON agentic_runtime.trigger_intake (agent_id, state, enqueued_at);

CREATE INDEX trigger_intake_lease_expires_idx
    ON agentic_runtime.trigger_intake (state, lease_expires_at)
    WHERE state = 'LEASED';

CREATE TABLE agentic_runtime.trigger_source_cursors (
    source_id TEXT NOT NULL,
    cursor_key TEXT NOT NULL,
    agent_id TEXT,
    cursor_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, cursor_key)
);

GRANT SELECT, INSERT, UPDATE ON
    agentic_runtime.trigger_intake,
    agentic_runtime.trigger_source_cursors
    TO agentic_runtime_lab_rw, agentic_runtime_shadow_rw;

GRANT SELECT ON
    agentic_runtime.trigger_intake,
    agentic_runtime.trigger_source_cursors
    TO agentic_runtime_reader;

COMMENT ON TABLE agentic_runtime.trigger_intake IS
    'Governed SHADOW trigger queue: deterministic producers enqueue; bounded drains lease and ack.';
COMMENT ON TABLE agentic_runtime.trigger_source_cursors IS
    'Per-source high-water cursors for deterministic trigger producers.';

COMMIT;
