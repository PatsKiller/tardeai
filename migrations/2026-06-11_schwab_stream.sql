-- Schwab streaming spike (Rule-9 ISOLATED): read-only market-data capture (L1 + Level-2 book).
-- Own tables, own daemon, NO imports into screeners/GO-WAIT/ATM/proposal generation. Proposals may READ
-- the derived book-pressure metrics later as additive evidence. No order streams anywhere.
CREATE TABLE IF NOT EXISTS schwab_stream_quotes (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    last NUMERIC, bid NUMERIC, ask NUMERIC,
    bid_size INT, ask_size INT, volume BIGINT,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssq_sym_ts ON schwab_stream_quotes (symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS schwab_stream_book (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    venue TEXT,                       -- NASDAQ_BOOK / NYSE_BOOK
    bid_depth NUMERIC,                -- sum(size) across captured bid levels
    ask_depth NUMERIC,
    imbalance NUMERIC,                -- (bid_depth-ask_depth)/(bid_depth+ask_depth)  [-1..1]
    best_bid NUMERIC, best_ask NUMERIC,
    bid_levels JSONB,                 -- top N [{price,size,mm_count}]
    ask_levels JSONB,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssb_sym_ts ON schwab_stream_book (symbol, captured_at DESC);
