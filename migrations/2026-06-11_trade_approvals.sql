-- Two-factor trade approvals (web + telegram, single-use, TTL) + standing live-enablement approvals.
-- The 4th and 3rd locks of the execution guard. Fully testable while execution stays BROKER_DISABLED.
CREATE TABLE IF NOT EXISTS trade_approvals (
    id BIGSERIAL PRIMARY KEY,
    intent_id UUID NOT NULL,
    correlation_id UUID NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('web','telegram')),
    code TEXT,                                   -- telegram one-time code (null for web)
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','confirmed','expired','consumed','superseded')),
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ta_intent ON trade_approvals (intent_id, channel, id DESC);

CREATE TABLE IF NOT EXISTS broker_live_approvals (   -- standing enablement records: NONE exist this phase
    id BIGSERIAL PRIMARY KEY,
    broker TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    scope TEXT NOT NULL,                             -- e.g. 'canary_window_2026-xx-xx'
    approved_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);
