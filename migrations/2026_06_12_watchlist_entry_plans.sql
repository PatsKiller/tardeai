-- Watchlist Entry Strategy (operator requirement 2026-06-12): actionable entry plans per
-- watchlist/incubator item — thesis, zone, limit, pullback logic, R:R, urgency — ADVISORY ONLY.
CREATE TABLE IF NOT EXISTS watchlist_entry_plans (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    plan JSONB NOT NULL,             -- full strict-JSON plan from the model
    setup_type TEXT,                 -- pullback | breakout | support_bounce | reversal
    entry_zone_low NUMERIC,
    entry_zone_high NUMERIC,
    limit_price NUMERIC,
    stop_price NUMERIC,
    target_price NUMERIC,
    risk_reward NUMERIC,
    urgency TEXT,                    -- watch | near_entry | ready
    confidence NUMERIC,
    proposal_tag TEXT,               -- WAIT | READY | NEEDS_CONFIRMATION (advisory; never executes)
    price_at_plan NUMERIC,
    model_used TEXT,
    prompt_version TEXT,
    alerted_at TIMESTAMPTZ,          -- telegram alert sent (proximity/readiness)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wep_sym ON watchlist_entry_plans (symbol, created_at DESC);
