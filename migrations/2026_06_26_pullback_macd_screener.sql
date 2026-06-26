-- Pullback + approaching-MACD-cross screener: S&P 500 uptrend dip-buy discovery.
-- Universe table + daily candidate results + run audit.

CREATE TABLE IF NOT EXISTS sp500_constituents (
    symbol        TEXT PRIMARY KEY,
    name          TEXT,
    sector        TEXT,
    active        BOOLEAN DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pullback_macd_candidates (
    id                 BIGSERIAL PRIMARY KEY,
    symbol             TEXT NOT NULL UNIQUE,
    tier               TEXT NOT NULL DEFAULT 'watch',   -- 'trigger' | 'watch'
    prev_tier          TEXT,
    price              NUMERIC,
    pullback_pct       NUMERIC,        -- % off 52-week high
    trend_pct          NUMERIC,        -- SMA50/SMA200 - 1 (uptrend strength)
    macd_prox_pct      NUMERIC,        -- |MACD-signal| as % of price (distance to cross)
    hist_rising_bars   INT,
    bars_to_cross_est  NUMERIC,
    rsi                NUMERIC,
    atr                NUMERIC,
    entry              NUMERIC,
    stop               NUMERIC,
    target1            NUMERIC,
    rr                 NUMERIC,
    score              NUMERIC,
    why_not            TEXT,           -- for watch tier: why the cross hasn't triggered
    proposal_id        INTEGER,        -- linked paper_trade_proposals.id if emitted
    payload            JSONB,
    status             TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'stale'
    scan_date          DATE,
    first_seen_at      TIMESTAMPTZ DEFAULT NOW(),
    last_scan_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pullback_macd_tier ON pullback_macd_candidates (status, tier, score DESC);
CREATE INDEX IF NOT EXISTS idx_pullback_macd_scan ON pullback_macd_candidates (scan_date DESC);

CREATE TABLE IF NOT EXISTS pullback_macd_runs (
    id              BIGSERIAL PRIMARY KEY,
    scan_date       DATE,
    universe_count  INT,
    screened        INT,
    uptrend_count   INT,
    pullback_count  INT,
    trigger_count   INT,
    watch_count     INT,
    proposals_emitted INT DEFAULT 0,
    data_errors     INT DEFAULT 0,
    duration_s      NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
