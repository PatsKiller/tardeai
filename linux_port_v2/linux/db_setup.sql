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

-- ── Personal Situation History (Phase P1) ──────────────────────────────────
-- Time-series of personal financial field changes.
-- One row per change event. Used by Phase 8D historical reconstruction.
CREATE TABLE IF NOT EXISTS personal_history (
    id             SERIAL PRIMARY KEY,
    field_name     TEXT NOT NULL,
    value          JSONB NOT NULL,
    data_type      TEXT NOT NULL,
    category       TEXT NOT NULL,
    effective_date DATE NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note           TEXT DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'live_write',
    CONSTRAINT personal_history_unique UNIQUE (field_name, effective_date, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_personal_field ON personal_history (field_name);
CREATE INDEX IF NOT EXISTS idx_personal_date  ON personal_history (effective_date DESC);
CREATE INDEX IF NOT EXISTS idx_personal_cat   ON personal_history (category);

-- View: field change timeline (used by Phase 8D)
CREATE OR REPLACE VIEW personal_timeline AS
    SELECT field_name, value, data_type, category, effective_date, recorded_at, note, source
    FROM personal_history
    ORDER BY field_name, recorded_at;

-- ── Performance Daily ───────────────────────────────────────────────────────
-- Computed period returns stored once per day. Derived from snapshots + Yahoo.
-- NOT a raw time-series (that's portfolio_snapshots). This stores the computed
-- 1D/1W/1M/3M/6M/YTD/1Y return percentages as of each day's pipeline run.
CREATE TABLE IF NOT EXISTS performance_daily (
    id serial PRIMARY KEY,
    snapshot_date date NOT NULL UNIQUE,
    total_value numeric(14,2) NOT NULL,
    change_1d_pct numeric(8,4),
    change_1w_pct numeric(8,4),
    change_1m_pct numeric(8,4),
    change_3m_pct numeric(8,4),
    change_6m_pct numeric(8,4),
    change_ytd_pct numeric(8,4),
    change_1y_pct numeric(8,4),
    data jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_performance_daily_date
    ON performance_daily(snapshot_date DESC);

-- ── Intel Briefs ────────────────────────────────────────────────────────────
-- Tracks every portfolio intelligence brief generated (daily, weekly, monthly).
CREATE TABLE IF NOT EXISTS intel_briefs (
    id serial PRIMARY KEY,
    brief_date date NOT NULL,
    brief_type varchar(20) NOT NULL,
    fund varchar(20) NOT NULL,
    docx_path text,
    word_count integer,
    sections jsonb NOT NULL,
    triggers jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(brief_date, brief_type, fund)
);
CREATE INDEX IF NOT EXISTS idx_brief_date ON intel_briefs(brief_date DESC);
CREATE INDEX IF NOT EXISTS idx_brief_fund ON intel_briefs(fund);

-- ── Action Signals History ──────────────────────────────────────────────────
-- Daily snapshot of per-ticker action signals. One row per ticker per day.
-- Enables queries like "how long has V been TRIM?" and signal frequency analysis.
CREATE TABLE IF NOT EXISTS action_signals_history (
    id serial PRIMARY KEY,
    signal_date date NOT NULL,
    symbol varchar(20) NOT NULL,
    signal varchar(10) NOT NULL,
    rule text,
    portfolio_pct numeric(6,3),
    market_value numeric(14,2),
    data jsonb,
    created_at timestamptz DEFAULT now(),
    UNIQUE(signal_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON action_signals_history(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON action_signals_history(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_action ON action_signals_history(signal);
