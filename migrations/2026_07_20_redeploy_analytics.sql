-- Redeploy analytics — dividend history for total-return math (Part C/D/E).
-- Price closes live in ticker_prices (price return only); distributions here.

CREATE TABLE IF NOT EXISTS ticker_dividends (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    ex_date DATE NOT NULL,
    amount NUMERIC NOT NULL CHECK (amount >= 0),
    source TEXT NOT NULL DEFAULT 'yfinance',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, ex_date)
);

CREATE INDEX IF NOT EXISTS idx_ticker_dividends_symbol ON ticker_dividends(symbol, ex_date DESC);

-- Fund/ETF facts (expense ratio, yield, category) with provenance + freshness.
CREATE TABLE IF NOT EXISTS instrument_facts (
    symbol TEXT PRIMARY KEY,
    instrument_name TEXT,
    quote_type TEXT,
    category TEXT,
    expense_ratio_pct NUMERIC,
    distribution_yield_pct NUMERIC,
    beta_3y NUMERIC,
    source TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE instrument_facts ADD COLUMN IF NOT EXISTS sector_weights JSONB;
ALTER TABLE instrument_facts ADD COLUMN IF NOT EXISTS top_holdings JSONB;
