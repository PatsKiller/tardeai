-- Hermes Phase 44 — Advisory Event Queue
-- Date: 2026-06-01
-- Purpose: Low-latency event queue for Hermes advisory context refresh

BEGIN;

CREATE TABLE IF NOT EXISTS hermes_advisory_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    source_table    TEXT NOT NULL,
    source_id       BIGINT NOT NULL,
    priority        TEXT NOT NULL DEFAULT 'normal',
    payload_hash    TEXT,
    event_status    TEXT NOT NULL DEFAULT 'pending',
    advisory_only   BOOLEAN NOT NULL DEFAULT true,
    not_execution   BOOLEAN NOT NULL DEFAULT true,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    latency_ms      INTEGER,
    error_message   TEXT,
    CONSTRAINT hermes_advisory_events_status_check CHECK (
        event_status IN ('pending','processing','completed','failed','skipped')
    ),
    CONSTRAINT hermes_advisory_events_advisory CHECK (advisory_only = true),
    CONSTRAINT hermes_advisory_events_no_exec CHECK (not_execution = true)
);

CREATE INDEX idx_hae_status ON hermes_advisory_events (event_status, created_at);
CREATE INDEX idx_hae_source ON hermes_advisory_events (source_table, source_id);

COMMENT ON TABLE hermes_advisory_events IS 'Low-latency advisory event queue — Phase 44. Advisory only, never execution.';

GRANT SELECT, INSERT, UPDATE ON hermes_advisory_events TO trade_ai;
GRANT USAGE ON SEQUENCE hermes_advisory_events_id_seq TO trade_ai;

COMMIT;
