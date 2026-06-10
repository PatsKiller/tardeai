-- Evidence-only: tests alternative entry/exit rules against actual fills. NEVER alters live strategy configs.
CREATE TABLE IF NOT EXISTS trade_execution_hypothesis_results (
    id BIGSERIAL PRIMARY KEY,
    trade_key TEXT, source TEXT, symbol TEXT, strategy_id TEXT,
    hypothesis TEXT,                         -- volume_confirmed_entry | hold_above_vwap | macd_rollover_exit
    actual_pnl_ps NUMERIC, variant_pnl_ps NUMERIC, delta_ps NUMERIC,
    improved BOOLEAN, applicable BOOLEAN,
    detail JSONB, created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (trade_key, source, hypothesis)
);
CREATE INDEX IF NOT EXISTS idx_teh_strat ON trade_execution_hypothesis_results (strategy_id, hypothesis);
