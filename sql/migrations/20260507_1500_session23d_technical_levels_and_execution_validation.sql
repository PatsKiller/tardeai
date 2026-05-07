-- Session 23D: Technical Levels, OHLCV Cache, and Execution Validation
-- Date: 2026-05-07
-- Purpose: Add OHLCV bar cache, enrich proposal technical snapshots with EMA/Fib/ORB,
--          and add execution validation fields for Alpaca paper bracket orders.

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. OHLCV Bar Cache
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS market_ohlcv_bars (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timeframe, bar_time)
);

CREATE INDEX IF NOT EXISTS idx_market_ohlcv_symbol_time
ON market_ohlcv_bars(symbol, timeframe, bar_time DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. Proposal Technical Snapshot — Additional Fields
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE proposal_technical_snapshots
ADD COLUMN IF NOT EXISTS ema_8_distance_pct NUMERIC,
ADD COLUMN IF NOT EXISTS ema_21_distance_pct NUMERIC,
ADD COLUMN IF NOT EXISTS ema_50_distance_pct NUMERIC,
ADD COLUMN IF NOT EXISTS ema_200_distance_pct NUMERIC,
ADD COLUMN IF NOT EXISTS swing_high NUMERIC,
ADD COLUMN IF NOT EXISTS swing_low NUMERIC,
ADD COLUMN IF NOT EXISTS swing_high_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS swing_low_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS fib_236 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_382 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_500 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_618 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_786 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_1272 NUMERIC,
ADD COLUMN IF NOT EXISTS fib_1618 NUMERIC,
ADD COLUMN IF NOT EXISTS nearest_fib_level TEXT,
ADD COLUMN IF NOT EXISTS nearest_fib_distance_pct NUMERIC,
ADD COLUMN IF NOT EXISTS opening_range_minutes INTEGER,
ADD COLUMN IF NOT EXISTS opening_range_status TEXT,
ADD COLUMN IF NOT EXISTS premarket_status TEXT,
ADD COLUMN IF NOT EXISTS intraday_data_source TEXT,
ADD COLUMN IF NOT EXISTS ohlcv_data_status TEXT;

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. Execution Readiness — Bracket Validation Fields
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE proposal_execution_readiness
ADD COLUMN IF NOT EXISTS bracket_order_supported BOOLEAN,
ADD COLUMN IF NOT EXISTS alpaca_account_mode TEXT,
ADD COLUMN IF NOT EXISTS alpaca_base_url_type TEXT,
ADD COLUMN IF NOT EXISTS market_hours BOOLEAN,
ADD COLUMN IF NOT EXISTS bracket_dry_run_payload JSONB,
ADD COLUMN IF NOT EXISTS paper_submit_tested BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS paper_submit_test_result TEXT;

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. Evidence Snapshot — Thesis Fields for Session 24
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE proposal_evidence_snapshots
ADD COLUMN IF NOT EXISTS technical_snapshot_id INTEGER,
ADD COLUMN IF NOT EXISTS execution_readiness_id INTEGER,
ADD COLUMN IF NOT EXISTS fib_context JSONB,
ADD COLUMN IF NOT EXISTS opening_range_status TEXT,
ADD COLUMN IF NOT EXISTS kill_conditions JSONB,
ADD COLUMN IF NOT EXISTS expected_hold_window TEXT,
ADD COLUMN IF NOT EXISTS expected_r NUMERIC;
