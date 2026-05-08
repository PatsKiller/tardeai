-- Session 23E: Market Quote Source Repair
-- Date: 2026-05-07
-- Purpose: Add multi-provider quote snapshot table for execution readiness

CREATE TABLE IF NOT EXISTS market_quote_snapshots (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_priority INTEGER,
    quote_timestamp TIMESTAMPTZ,
    last_price NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    bid_size NUMERIC,
    ask_size NUMERIC,
    spread NUMERIC,
    spread_pct NUMERIC,
    day_volume NUMERIC,
    minute_volume NUMERIC,
    vwap NUMERIC,
    is_delayed BOOLEAN DEFAULT false,
    is_execution_eligible BOOLEAN DEFAULT false,
    raw_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mqs_symbol_created
ON market_quote_snapshots(symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mqs_provider_created
ON market_quote_snapshots(provider, created_at DESC);

ALTER TABLE proposal_execution_readiness
ADD COLUMN IF NOT EXISTS quote_provider TEXT,
ADD COLUMN IF NOT EXISTS quote_snapshot_id INTEGER,
ADD COLUMN IF NOT EXISTS quote_is_delayed BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS quote_execution_eligible BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS volume_source TEXT,
ADD COLUMN IF NOT EXISTS spread_source TEXT;
