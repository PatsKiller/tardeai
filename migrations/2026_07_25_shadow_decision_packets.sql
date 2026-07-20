-- 2026_07_25_shadow_decision_packets.sql
-- Stage A: append-only persistence for the multidimensional decision packet.
--
-- SHADOW ONLY. Nothing in this schema feeds the production Command Center card,
-- proposal eligibility, or any execution path. It exists so the new architecture
-- can be generated, persisted and inspected alongside the legacy one-word
-- verdict before anything is switched over.
--
-- Append-only by design: a packet is never updated in place. A re-evaluation
-- writes a NEW row and marks the prior one superseded. The BETA incident turned
-- on a verdict that flipped four times in 106 minutes with no history — the
-- instability was invisible because each write overwrote the last.

BEGIN;

CREATE TABLE IF NOT EXISTS decision_runs (
    run_id           BIGSERIAL PRIMARY KEY,
    origin           TEXT NOT NULL,              -- scheduled | on_demand | test
    requested_by     TEXT,
    requested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    state            TEXT NOT NULL DEFAULT 'QUEUED',   -- QUEUED|RUNNING|COMPLETE|FAILED
    symbols_requested INT DEFAULT 0,
    symbols_completed INT DEFAULT 0,
    provider_requested TEXT,
    provider_used      TEXT,
    fallback_reason    TEXT,
    failure_reason     TEXT,
    source_commit_sha  TEXT
);

CREATE TABLE IF NOT EXISTS decision_packets (
    packet_id        BIGSERIAL PRIMARY KEY,
    run_id           BIGINT REFERENCES decision_runs(run_id),
    symbol           TEXT NOT NULL,
    packet_version   TEXT NOT NULL,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    facts_as_of      TIMESTAMPTZ,
    price_used       NUMERIC,
    current_price    NUMERIC,
    price_drift_pct  NUMERIC,
    instrument_type  TEXT,

    -- Dimension summaries, denormalised for query without unpacking the JSON.
    thesis_state     TEXT,
    swing_timing     TEXT,
    tactical_timing  TEXT,
    event_state      TEXT,
    data_quality     TEXT,
    actionable       BOOLEAN NOT NULL DEFAULT false,

    -- Per-family state. Every family is ALWAYS present, never null, so a missing
    -- family is a schema violation rather than a silent omission.
    family_long_term TEXT NOT NULL,
    family_swing     TEXT NOT NULL,
    family_bearish   TEXT NOT NULL,
    family_options   TEXT NOT NULL,
    no_trade_valid   BOOLEAN NOT NULL DEFAULT true,

    model_review_mode TEXT,
    lanes_requested   INT DEFAULT 0,
    lanes_completed   INT DEFAULT 0,

    packet           JSONB NOT NULL,
    source_commit_sha TEXT,
    superseded_by    BIGINT REFERENCES decision_packets(packet_id),
    superseded_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_decision_packets_symbol_generated
    ON decision_packets (upper(symbol), generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_packets_live
    ON decision_packets (upper(symbol)) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_decision_packets_run ON decision_packets (run_id);

CREATE TABLE IF NOT EXISTS decision_blueprints (
    blueprint_id     BIGSERIAL PRIMARY KEY,
    packet_id        BIGINT NOT NULL REFERENCES decision_packets(packet_id) ON DELETE CASCADE,
    symbol           TEXT NOT NULL,
    family           TEXT NOT NULL,      -- LONG_TERM|SWING|BEARISH|OPTIONS|NO_TRADE
    structure        TEXT NOT NULL,
    state            TEXT NOT NULL,      -- ELIGIBLE|CONDITIONAL|REJECTED|NOT_APPLICABLE|DATA_UNAVAILABLE
    mechanics        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- A REJECTED or DATA_UNAVAILABLE row with an empty reasons array is the
    -- defect this column exists to make visible: a refusal that does not state
    -- its cause is indistinguishable from an oversight.
    rejection_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    quote_as_of      TIMESTAMPTZ,
    quote_source     TEXT,
    event_state      TEXT,
    eligibility      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_decision_blueprints_packet ON decision_blueprints (packet_id);
CREATE INDEX IF NOT EXISTS idx_decision_blueprints_symbol_family
    ON decision_blueprints (upper(symbol), family);

-- Structured contradiction log from position_truth. Deliberately a table rather
-- than prose inside a synthesis field: the existing card-side suppression parses
-- free text, which works today and stops working silently if wording changes.
CREATE TABLE IF NOT EXISTS position_truth_contradictions (
    id               BIGSERIAL PRIMARY KEY,
    symbol           TEXT NOT NULL,
    agent            TEXT,
    kind             TEXT NOT NULL,      -- PHANTOM_POSITION|SIZE_MISMATCH|DISPOSAL_OF_NOTHING
    severity         TEXT NOT NULL,
    detail           TEXT,
    evidence         TEXT,
    recommendation   TEXT,
    ownership_snapshot JSONB,
    packet_id        BIGINT REFERENCES decision_packets(packet_id),
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_position_truth_symbol
    ON position_truth_contradictions (upper(symbol), detected_at DESC);

COMMIT;
