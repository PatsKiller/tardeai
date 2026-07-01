-- Speed latest-quote lookups used by Command Center Portfolio and stop preflight.
-- Apply outside a transaction because CREATE INDEX CONCURRENTLY requires it.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_market_quotes_symbol_fetched_at_desc
    ON market_quotes (symbol, fetched_at DESC);
