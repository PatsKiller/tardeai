-- Active Trader Stage 1 · 0004 broker capability + rejection fabric (up)
-- Unsupported/unknown stay EXPLICIT; stale evidence can never read as SUPPORTED
-- (expiry is checked by the contract layer; rows keep their raw state + expiry).

CREATE TABLE broker_account_capabilities (
    broker              TEXT NOT NULL CHECK (broker IN ('alpaca','moomoo','schwab')),
    account_label       TEXT NOT NULL,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    capability          TEXT NOT NULL,
    state               TEXT NOT NULL CHECK (state IN ('SUPPORTED','UNSUPPORTED','UNKNOWN','DEGRADED','RESTRICTED')),
    source              TEXT NOT NULL CHECK (source IN ('DOCUMENTATION','RUNTIME_PROBE','BROKER_RESPONSE','OPERATOR_OVERRIDE')),
    verified_at         TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    adapter_version     TEXT,
    evidence_ref        TEXT,
    notes               TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (broker, account_label, environment, capability),
    -- A claim of SUPPORTED requires evidence time; UNKNOWN needs none:
    CHECK (state <> 'SUPPORTED' OR verified_at IS NOT NULL)
);

CREATE TABLE broker_rejection_events (
    rejection_event_id  UUID PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    broker              TEXT NOT NULL CHECK (broker IN ('alpaca','moomoo','schwab')),
    account_label       TEXT NOT NULL,
    symbol              TEXT,
    order_intent_id     UUID,
    raw_status          TEXT,
    raw_code            TEXT,
    raw_message         TEXT,
    normalized_code     TEXT NOT NULL,
    retryable           BOOLEAN NOT NULL DEFAULT false,   -- unknown rejections default non-retryable
    requires_operator   BOOLEAN NOT NULL DEFAULT true,
    requires_broker_call BOOLEAN NOT NULL DEFAULT false,
    affected_capability TEXT,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ,
    evidence_hash       TEXT
);

CREATE INDEX idx_broker_rejections_lookup ON broker_rejection_events (broker, account_label, symbol, normalized_code);
