-- Active Trader Stage 1 · 0001 sessions (up)
-- Session drafts are APPEND-ONLY versioned rows; an authorization binds one
-- immutable draft hash. environment has NO default anywhere (Law: no implicit LIVE).

CREATE TABLE active_trader_session_drafts (
    draft_id            UUID NOT NULL,
    draft_version       INTEGER NOT NULL CHECK (draft_version >= 1),
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    session_name        TEXT NOT NULL,
    broker_set          JSONB NOT NULL,
    account_policy      JSONB NOT NULL,          -- accounts, PRIMARY/FALLBACK/DISABLED, quantities, allocation mode
    symbol_policy       JSONB NOT NULL,          -- explicit list OR versioned universe rule
    risk_limits         JSONB NOT NULL,          -- max_trades, max_concurrent, gross notional, per-trade risk, daily loss, chase bps, order ttl
    time_bounds         JSONB NOT NULL,          -- session_start, entry_cutoff, expiry, allowed sessions
    runner_policy       JSONB NOT NULL,
    feature_policy_versions JSONB NOT NULL,      -- candidate_rule/ticket_policy/model_review versions
    draft_hash          TEXT NOT NULL,           -- sha256 of canonical draft payload
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (draft_id, draft_version),
    UNIQUE (draft_hash)
);

CREATE OR REPLACE FUNCTION active_trader_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'active_trader: % rows are append-only (no % allowed)', TG_TABLE_NAME, TG_OP;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_session_drafts_append_only
    BEFORE UPDATE OR DELETE ON active_trader_session_drafts
    FOR EACH ROW EXECUTE FUNCTION active_trader_forbid_mutation();

CREATE TABLE active_trader_session_authorizations (
    session_authorization_id UUID PRIMARY KEY,
    draft_id            UUID NOT NULL,
    draft_version       INTEGER NOT NULL,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    authorization_hash  TEXT NOT NULL UNIQUE,    -- binds the exact draft_hash + operator + time bounds
    draft_hash          TEXT NOT NULL,
    operator_id         TEXT NOT NULL,
    two_fa_ref          TEXT,                    -- populated by a LATER stage; Stage 1 stores contract only
    status              TEXT NOT NULL CHECK (status IN ('PENDING','AUTHORIZED','ACTIVE','PAUSED','ENTRY_CUTOFF','DRAINING','REVOKED','EXPIRED','CLOSED')),
    session_start       TIMESTAMPTZ NOT NULL,
    session_entry_cutoff TIMESTAMPTZ NOT NULL,
    session_expiry      TIMESTAMPTZ NOT NULL,
    authorized_at       TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ,
    revoke_reason       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (draft_id, draft_version) REFERENCES active_trader_session_drafts (draft_id, draft_version),
    CHECK (session_entry_cutoff <= session_expiry),
    CHECK (status <> 'REVOKED' OR revoked_at IS NOT NULL)
);

CREATE TABLE active_trader_session_accounts (
    session_authorization_id UUID NOT NULL REFERENCES active_trader_session_authorizations (session_authorization_id),
    broker              TEXT NOT NULL CHECK (broker IN ('alpaca','moomoo','schwab')),
    account_label       TEXT NOT NULL,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    role                TEXT NOT NULL CHECK (role IN ('PRIMARY','FALLBACK','DISABLED')),
    max_shares          NUMERIC CHECK (max_shares IS NULL OR max_shares >= 0),
    max_notional        NUMERIC CHECK (max_notional IS NULL OR max_notional >= 0),
    max_risk            NUMERIC CHECK (max_risk IS NULL OR max_risk >= 0),
    fallback_priority   INTEGER,
    PRIMARY KEY (session_authorization_id, broker, account_label)
);
