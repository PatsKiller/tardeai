CREATE TABLE IF NOT EXISTS analyst_data_history (
    id SERIAL PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    asset_type TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analyst_data_history_symbol ON analyst_data_history(symbol);
CREATE INDEX IF NOT EXISTS idx_analyst_data_history_asof ON analyst_data_history(as_of DESC);

CREATE TABLE IF NOT EXISTS asset_intelligence_history (
    id SERIAL PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_asset_intelligence_symbol ON asset_intelligence_history(symbol);
CREATE INDEX IF NOT EXISTS idx_asset_intelligence_type ON asset_intelligence_history(asset_type);
CREATE INDEX IF NOT EXISTS idx_asset_intelligence_asof ON asset_intelligence_history(as_of DESC);

CREATE TABLE IF NOT EXISTS discovery_candidates_history (
    id SERIAL PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    bucket TEXT NOT NULL,
    score NUMERIC(8,3),
    source TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, bucket, as_of)
);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_symbol ON discovery_candidates_history(symbol);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_bucket ON discovery_candidates_history(bucket);

CREATE TABLE IF NOT EXISTS ai_watchlist_history (
    id SERIAL PRIMARY KEY,
    as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    bucket TEXT NOT NULL,
    action TEXT NOT NULL,
    score NUMERIC(8,3),
    thesis TEXT,
    trade_plan JSONB,
    review_status TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ai_watchlist_symbol ON ai_watchlist_history(symbol);
CREATE INDEX IF NOT EXISTS idx_ai_watchlist_asof ON ai_watchlist_history(as_of DESC);
