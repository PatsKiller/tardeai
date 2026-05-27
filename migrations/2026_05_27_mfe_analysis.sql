-- MFE/MAE analysis + entry quality scoring
CREATE TABLE IF NOT EXISTS trade_mfe_analysis (
    id                  BIGSERIAL PRIMARY KEY,
    trade_id            INTEGER NOT NULL,
    symbol              TEXT NOT NULL,
    strategy_id         TEXT,
    mfe_price           NUMERIC,
    mfe_r               NUMERIC,
    mfe_time            TIMESTAMPTZ,
    mfe_bar_index       INTEGER,
    mae_price           NUMERIC,
    mae_r               NUMERIC,
    mae_time            TIMESTAMPTZ,
    mae_bar_index       INTEGER,
    capture_ratio       NUMERIC,
    money_left          NUMERIC,
    optimal_exit_price  NUMERIC,
    optimal_exit_time   TIMESTAMPTZ,
    stop_nearly_hit     BOOLEAN DEFAULT false,
    stop_distance_at_mae NUMERIC,
    bars_analyzed       INTEGER,
    holding_period_min  INTEGER,
    entry_quality_score NUMERIC,
    slippage_score      NUMERIC,
    timing_score        NUMERIC,
    setup_score         NUMERIC,
    context_score       NUMERIC,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trade_mfe_trade ON trade_mfe_analysis(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_mfe_strategy ON trade_mfe_analysis(strategy_id);

-- Trailing stop optimization results
CREATE TABLE IF NOT EXISTS trailing_optimization_results (
    id              BIGSERIAL PRIMARY KEY,
    strategy_family TEXT NOT NULL,
    current_config  JSONB,
    optimized_config JSONB,
    current_avg_r   NUMERIC,
    optimized_avg_r NUMERIC,
    improvement_pct NUMERIC,
    sample_size     INTEGER,
    confidence      TEXT,
    detail          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
