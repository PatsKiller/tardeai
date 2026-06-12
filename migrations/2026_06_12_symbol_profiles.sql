-- One-sentence company profiles + sector for every watch-grade symbol (operator 2026-06-12:
-- "sentence on what company does" on all watchlist/open-trades/portfolio cards).
CREATE TABLE IF NOT EXISTS symbol_profiles (
    symbol TEXT PRIMARY KEY,
    description_1s TEXT,            -- first sentence of the business summary (display-sized)
    sector TEXT,
    industry TEXT,
    source TEXT,                    -- yfinance | proxy_label | manual
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
