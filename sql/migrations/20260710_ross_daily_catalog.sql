-- Ross Cameron / Warrior Trading daily winner catalog (Hermes extraction target)
CREATE TABLE IF NOT EXISTS ross_daily_catalog (
    id                  SERIAL PRIMARY KEY,
    trade_date          DATE NOT NULL,
    video_id            TEXT NOT NULL,
    video_title         TEXT,
    video_publish_date  DATE,
    symbols_traded      TEXT[] NOT NULL DEFAULT '{}',
    winners             JSONB NOT NULL DEFAULT '[]',
    losers              JSONB NOT NULL DEFAULT '[]',
    net_pnl_usd         REAL,
    account_size_usd    REAL,
    setup_types         TEXT[] DEFAULT '{}',
    scanner_filters     TEXT,
    extraction_method   TEXT NOT NULL DEFAULT 'regex',
    extraction_confidence REAL,
    hermes_review_json  JSONB,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trade_date, video_id)
);

CREATE INDEX IF NOT EXISTS idx_ross_catalog_trade_date ON ross_daily_catalog(trade_date);
CREATE INDEX IF NOT EXISTS idx_ross_catalog_video ON ross_daily_catalog(video_id);