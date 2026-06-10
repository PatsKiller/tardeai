-- Replay-aware execution quality (additive analytics; read-only; no trading writes). Unified over Schwab
-- round-trips + paper trades. Computed metrics live here; Grok interpretation is stored SEPARATELY.
CREATE TABLE IF NOT EXISTS trade_execution_quality (
    id BIGSERIAL PRIMARY KEY,
    trade_key TEXT NOT NULL,
    source TEXT NOT NULL,                 -- schwab_round_trip | paper_trade
    broker TEXT, account TEXT, symbol TEXT, strategy_id TEXT,
    entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ,
    entry_price NUMERIC, exit_price NUMERIC, qty NUMERIC,
    realized_pnl NUMERIC, realized_r NUMERIC, hold_minutes NUMERIC,
    bar_interval TEXT, bars_source TEXT, bars_count INT,
    path_status TEXT,                     -- OK | NO_INTRADAY_PATH | NO_VOLUME_DATA | INSUFFICIENT_BARS
    entry_volume_confirmed BOOLEAN, entry_volume_ratio NUMERIC, entry_relative_volume_window INT,
    entry_above_vwap BOOLEAN, entry_vwap_distance_pct NUMERIC,
    entry_macd_state TEXT, entry_rsi NUMERIC,
    entry_timing_grade TEXT, exit_timing_grade TEXT,
    execution_grade TEXT, outcome_grade TEXT, discipline_grade TEXT, missed_opportunity_grade TEXT,
    mfe_after_entry NUMERIC, mae_after_entry NUMERIC,
    mfe_after_exit NUMERIC, mfe_after_exit_pct NUMERIC,
    post_exit_high NUMERIC, post_exit_high_time TIMESTAMPTZ,
    capture_ratio NUMERIC, available_profit NUMERIC, captured_profit NUMERIC,
    missed_profit NUMERIC, missed_profit_pct NUMERIC,
    premature_exit_flag BOOLEAN, early_entry_flag BOOLEAN, late_entry_flag BOOLEAN, no_volume_entry_flag BOOLEAN,
    strategy_rule_violations JSONB, computed_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trade_key, source)
);
CREATE TABLE IF NOT EXISTS trade_execution_grok_reviews (
    id BIGSERIAL PRIMARY KEY,
    trade_key TEXT NOT NULL, source TEXT NOT NULL,
    model_lane TEXT, prompt_version TEXT,
    computed_metrics_snapshot JSONB,
    grok_execution_label TEXT, grok_summary TEXT, grok_mistakes JSONB,
    grok_what_to_do_next_time TEXT, grok_strategy_backtest_hypotheses JSONB,
    normalized_tags JSONB, confidence NUMERIC, review_status TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trade_key, source)
);
CREATE INDEX IF NOT EXISTS idx_teq_symbol ON trade_execution_quality (symbol, source);
