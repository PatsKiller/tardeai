-- Single-source-of-truth position/basis layer (operator decision 2026-06-12, after the SCHG/SCHD
-- basis audit): Schwab API positions land in the DB; holdings.json basis derives from here
-- (csv tax lots > broker API averagePrice > nothing; CSV reconstruction demoted to Fidelity-only).
CREATE TABLE IF NOT EXISTS schwab_positions_live (
    id BIGSERIAL PRIMARY KEY,
    account_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_price NUMERIC,                 -- Schwab averagePrice: broker's own average cost
    market_value NUMERIC,
    unrealized_pl NUMERIC,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_key, symbol)
);
CREATE INDEX IF NOT EXISTS idx_spl_captured ON schwab_positions_live (captured_at DESC);
