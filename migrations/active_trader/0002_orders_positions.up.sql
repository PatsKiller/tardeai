-- Active Trader Stage 1 · 0002 order intents + position states (up)
-- LIVE intents are representable ONLY with a session authorization + hash (DB-enforced).
-- idempotency_key is globally unique: a simulation identifier can never be reused for live.

CREATE TABLE active_trader_order_intents (
    order_intent_id     UUID PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    session_authorization_id UUID REFERENCES active_trader_session_authorizations (session_authorization_id),
    authorization_hash  TEXT,
    broker              TEXT NOT NULL CHECK (broker IN ('alpaca','moomoo','schwab')),
    account_label       TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity            NUMERIC NOT NULL CHECK (quantity > 0),
    order_type          TEXT NOT NULL CHECK (order_type IN ('LIMIT','MARKET','STOP','STOP_LIMIT','MARKETABLE_LIMIT')),
    limit_price         NUMERIC,
    stop_price          NUMERIC,
    time_in_force       TEXT NOT NULL,
    trading_session     TEXT NOT NULL CHECK (trading_session IN ('RTH','PRE','POST','OVERNIGHT')),
    idempotency_key     TEXT NOT NULL UNIQUE,
    input_hash          TEXT NOT NULL,
    parent_intent_id    UUID REFERENCES active_trader_order_intents (order_intent_id),
    status              TEXT NOT NULL CHECK (status IN ('DRAFT','VALIDATED','AUTHORIZED','STAGED','SUBMITTED','PARTIAL','FILLED','CANCELLED','REJECTED','EXPIRED')),
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- SHADOW rows may never carry broker-write authorization state:
    CHECK (environment <> 'SHADOW' OR status IN ('DRAFT','VALIDATED','EXPIRED')),
    -- No LIVE intent without a bound, hash-carrying session authorization:
    CHECK (environment <> 'LIVE' OR (session_authorization_id IS NOT NULL AND authorization_hash IS NOT NULL))
);

CREATE INDEX idx_at_order_intents_session ON active_trader_order_intents (session_authorization_id);
CREATE INDEX idx_at_order_intents_symbol ON active_trader_order_intents (symbol, environment);

CREATE TABLE active_trader_position_states (
    position_state_id   UUID PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    session_authorization_id UUID REFERENCES active_trader_session_authorizations (session_authorization_id),
    broker              TEXT NOT NULL CHECK (broker IN ('alpaca','moomoo','schwab')),
    account_label       TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    state               TEXT NOT NULL CHECK (state IN ('WORKING','FILLED','PROTECTED','MANAGING','SCALING','RUNNER_CANDIDATE','RUNNER_CONFIRMED','EXITING','FLAT')),
    quantity            NUMERIC NOT NULL,
    avg_entry           NUMERIC,
    protection_state    TEXT NOT NULL CHECK (protection_state IN ('NONE','PENDING','CONFIRMED','UNCERTAIN','FAILED')),
    resilience_score    NUMERIC,
    resistance_score    NUMERIC,
    feature_snapshot_ref TEXT,
    policy_version      TEXT,
    as_of               TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment <> 'LIVE' OR session_authorization_id IS NOT NULL)
);

CREATE INDEX idx_at_position_states_lookup ON active_trader_position_states (symbol, environment, as_of DESC);
