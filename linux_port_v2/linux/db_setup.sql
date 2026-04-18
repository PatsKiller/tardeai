-- ============================================================
--  Trade AI v12 + Portfolio Intelligence v1.2
--  PostgreSQL Schema — Linux only
--  Run once: psql -U trade_ai -d trade_ai -f linux/db_setup.sql
-- ============================================================

-- ── Holdings ─────────────────────────────────────────────────────────────────
-- Stores full portfolio dict (all 4 accounts + holdings + transactions)
-- One row per day (upsert on as_of date)
CREATE TABLE IF NOT EXISTS holdings (
    id          SERIAL PRIMARY KEY,
    as_of       DATE NOT NULL,
    data        JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT holdings_as_of_unique UNIQUE (as_of)
);
CREATE INDEX IF NOT EXISTS idx_holdings_as_of ON holdings (as_of DESC);

-- ── Price Cache ───────────────────────────────────────────────────────────────
-- Yahoo Finance closing prices: one row per symbol per trading day
-- Covers last 2 years (~112,500 rows for 75 symbols)
CREATE TABLE IF NOT EXISTS price_cache (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(10) NOT NULL,
    price_date  DATE NOT NULL,
    close_price NUMERIC(12,4) NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT price_cache_symbol_date_unique UNIQUE (symbol, price_date)
);
CREATE INDEX IF NOT EXISTS idx_price_cache_symbol ON price_cache (symbol);
CREATE INDEX IF NOT EXISTS idx_price_cache_date   ON price_cache (price_date DESC);
CREATE INDEX IF NOT EXISTS idx_price_cache_lookup ON price_cache (symbol, price_date DESC);

-- ── Portfolio Snapshots ───────────────────────────────────────────────────────
-- Daily portfolio value snapshots for period return calculation
-- One row per day, grows indefinitely
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id             SERIAL PRIMARY KEY,
    snapshot_date  DATE NOT NULL,
    total_value    NUMERIC(14,2) NOT NULL,
    source         VARCHAR(20) DEFAULT 'live',
    data           JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT portfolio_snapshots_date_unique UNIQUE (snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON portfolio_snapshots (snapshot_date DESC);

-- ── Trade AI State ────────────────────────────────────────────────────────────
-- Delta tracking state: one row per ticker per run date
-- Replaces data/state.json. All historical runs kept.
CREATE TABLE IF NOT EXISTS trade_ai_state (
    id         SERIAL PRIMARY KEY,
    run_date   DATE NOT NULL,
    ticker     VARCHAR(10) NOT NULL,
    data       JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT trade_ai_state_date_ticker UNIQUE (run_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_state_run_date ON trade_ai_state (run_date DESC);
CREATE INDEX IF NOT EXISTS idx_state_ticker   ON trade_ai_state (ticker);

-- ── Run Summary ───────────────────────────────────────────────────────────────
-- One row per Trade AI pipeline run. All historical runs kept.
-- When large: normalize meta columns out and purge old data JSONB.
CREATE TABLE IF NOT EXISTS run_summary (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL,
    run_label   VARCHAR(20) NOT NULL,
    go_count    INTEGER DEFAULT 0,
    wait_count  INTEGER DEFAULT 0,
    data        JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT run_summary_date_label UNIQUE (run_date, run_label)
);
CREATE INDEX IF NOT EXISTS idx_run_summary_date ON run_summary (run_date DESC);

-- ── Utility views ─────────────────────────────────────────────────────────────

-- Latest holdings (most recent as_of date)
CREATE OR REPLACE VIEW latest_holdings AS
    SELECT data FROM holdings ORDER BY as_of DESC LIMIT 1;

-- Price cache coverage (useful for debugging)
CREATE OR REPLACE VIEW price_cache_coverage AS
    SELECT
        symbol,
        COUNT(*) AS trading_days,
        MIN(price_date) AS earliest,
        MAX(price_date) AS latest,
        MAX(updated_at) AS last_updated
    FROM price_cache
    GROUP BY symbol
    ORDER BY symbol;

-- Recent run performance
CREATE OR REPLACE VIEW recent_runs AS
    SELECT run_date, run_label, go_count, wait_count, created_at
    FROM run_summary
    ORDER BY run_date DESC, run_label
    LIMIT 30;

-- ── Done ──────────────────────────────────────────────────────────────────────
-- Verify:
--   \dt                           -- list tables
--   SELECT * FROM price_cache_coverage;
--   SELECT COUNT(*) FROM holdings;
