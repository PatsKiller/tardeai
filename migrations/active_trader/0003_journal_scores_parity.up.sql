-- Active Trader Stage 1 · 0003 journal, score snapshots, parity checks (up)
-- Journal is APPEND-ONLY event sourcing (§16D.1).

CREATE TABLE active_trader_journal_events (
    journal_event_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    event_type          TEXT NOT NULL,
    session_authorization_id UUID,
    order_intent_id     UUID,
    symbol              TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_snapshot_ref TEXT,
    replay_segment_ref  TEXT,
    policy_version      TEXT,
    code_sha            TEXT,
    authorization_hash  TEXT,
    occurred_at         TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_at_journal_events_session ON active_trader_journal_events (session_authorization_id, occurred_at);
CREATE INDEX idx_at_journal_events_type ON active_trader_journal_events (event_type, occurred_at);

CREATE TRIGGER trg_journal_events_append_only
    BEFORE UPDATE OR DELETE ON active_trader_journal_events
    FOR EACH ROW EXECUTE FUNCTION active_trader_forbid_mutation();

CREATE TABLE active_trader_score_snapshots (
    score_snapshot_id   UUID PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    subject_type        TEXT NOT NULL CHECK (subject_type IN ('FIRE','ENTRY','MANAGEMENT','SCALE','RUNNER','EXIT','SESSION')),
    subject_ref         TEXT NOT NULL,
    scores              JSONB NOT NULL,
    scoring_version     TEXT NOT NULL,
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE active_trader_parity_checks (
    parity_check_id     UUID PRIMARY KEY,
    check_kind          TEXT NOT NULL,           -- quote/candidate/session/order/position/pnl/risk/hash/kill/journal_count
    classic_value       JSONB,
    next_value          JSONB,
    matched             BOOLEAN NOT NULL,
    detail              TEXT,
    checked_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
