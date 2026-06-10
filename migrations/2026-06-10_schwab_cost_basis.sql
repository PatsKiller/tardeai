-- Authoritative Schwab cost basis (Realized + Unrealized Gain/Loss export from schwab.com Cost Basis tab).
-- The Trader API exposes ONLY average price (no tax lots), so this operator-provided export is the
-- authoritative source above both API average price and hand-entered overrides. Read-only ingest; basis
-- writes to holdings still go through the authorized writer (Gate B). No trading writes.
CREATE TABLE IF NOT EXISTS schwab_cost_basis_lots (
    id BIGSERIAL PRIMARY KEY,
    account TEXT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 'realized' | 'unrealized'
    quantity NUMERIC,
    opened_date DATE,
    closed_date DATE,               -- realized only
    cost_per_share NUMERIC,
    cost_basis NUMERIC,
    proceeds NUMERIC,               -- realized only
    realized_gain NUMERIC,          -- realized only
    term TEXT,                      -- 'short' | 'long'
    wash_sale BOOLEAN DEFAULT FALSE,
    source_file TEXT,
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_scb_symbol ON schwab_cost_basis_lots (symbol, account, kind);
